"""Drive genuine Codex conversations with synthetic memory and retained wire evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
PRODUCER = "verify-twinaatma.host/v1"


def sha(path):
    path=Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def product_hashes():
    paths=[*ROOT.glob("knowledgeos/*.py"), *ROOT.glob(".cursor/hooks/*.py"), ROOT/"AGENTS.md"]
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)}


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def proxy(log,command):
    lock=threading.Lock()
    def record(value):
        with lock:
            with log.open("a",encoding="utf-8") as out:out.write(json.dumps(value,ensure_ascii=False)+"\n")
    child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    record({"kind":"process","proxy_pid":os.getpid(),"pid":child.pid,"command":command})
    def output():
        for raw in child.stdout:
            try:record({"kind":"response","message":json.loads(raw)})
            except ValueError:record({"kind":"non_json","direction":"response","bytes":len(raw)})
            try:sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()
            except (OSError,ValueError):break
    def errors():
        for raw in child.stderr:
            record({"kind":"stderr","text":raw.decode("utf-8",errors="replace")})
    output_thread=threading.Thread(target=output,daemon=True);output_thread.start()
    error_thread=threading.Thread(target=errors,daemon=True);error_thread.start()
    try:
        for raw in sys.stdin.buffer:
            try:record({"kind":"request","message":json.loads(raw)})
            except ValueError:record({"kind":"non_json","direction":"request","bytes":len(raw)})
            child.stdin.write(raw);child.stdin.flush()
    finally:
        child.stdin.close()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        output_thread.join(timeout=10);error_thread.join(timeout=10)
        record({"kind":"exit","pid":child.pid,"exit_code":child.returncode})
    return child.returncode



def collect_shutdown(paths, timeout=30):
    from knowledgeos.locking import _dead
    deadline=time.monotonic()+timeout
    paths=list(paths)
    initial={path:rows(path) for path in paths}
    pids={record[key] for records in initial.values() for record in records
          if record.get("kind")=="process" for key in ("pid","proxy_pid")}
    while any(not _dead(pid) for pid in pids):
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        time.sleep(min(.05,remaining))
    processes=[]
    for path in paths:
        records=rows(path)
        exits={r.get("pid"):r.get("exit_code") for r in records if r.get("kind")=="exit"}
        for record in records:
            if record.get("kind")!="process":continue
            for key in ("pid","proxy_pid"):
                pid=record[key]
                processes.append({"pid":pid,"role":key,"stopped":_dead(pid),"exit_code":exits.get(pid)})
    return processes

def calls_from_wire(records):
    responses={r["message"].get("id"):r["message"] for r in records if r.get("kind")=="response"}
    calls=[]
    for record in records:
        message=record.get("message",{})
        if record.get("kind")!="request" or message.get("method")!="tools/call":continue
        params=message.get("params",{});response=responses.get(message.get("id"),{})
        result=response.get("result",{});payload={}
        try:payload=json.loads(result.get("content",[])[0]["text"])
        except (ValueError,KeyError,IndexError):pass
        calls.append({"name":params.get("name"),"arguments":params.get("arguments",{}),
                      "payload":payload,"ok":bool(result) and not result.get("isError") and not response.get("error")})
    return calls


def session_pair(calls):
    starts=[c for c in calls if c["name"]=="memory_session_start" and c["ok"]]
    ends=[c for c in calls if c["name"]=="memory_session_end" and c["ok"]]
    if len(starts)!=1 or len(ends)!=1:return None
    sid=starts[0]["payload"].get("session_id")
    if not sid or ends[0]["arguments"].get("session_id")!=sid or ends[0]["payload"].get("session_id")!=sid:return None
    return sid,ends[0]


def summary_saved(vault,receipt,summary):
    if not isinstance(receipt,dict) or receipt.get("ok") is not True:return False
    path=receipt.get("path")
    if not isinstance(path,str) or not path.strip() or "\\" in path:return False
    if not isinstance(summary,str) or not summary.strip():return False
    relative=PurePosixPath(path)
    if (relative.is_absolute() or len(relative.parts)<2 or relative.parts[0]!="Inbox"
            or any(part in (".","..") or ":" in part for part in relative.parts)
            or relative.as_posix()!=path or relative.suffix!=".md"):return False
    try:
        current=Path(vault)
        components=[current]
        for part in relative.parts:
            current=current/part;components.append(current)
        for component in components:
            info=component.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)
                    & getattr(stat,"FILE_ATTRIBUTE_REPARSE_POINT",0)):return False
            if component==current:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:return False
            elif not stat.S_ISDIR(info.st_mode):return False
        descriptor=os.open(current,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))
        with os.fdopen(descriptor,"rb") as stream:
            opened=os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink!=1
                    or (opened.st_dev,opened.st_ino)!=(info.st_dev,info.st_ino)):return False
            text=stream.read().decode("utf-8").replace("\r\n","\n").replace("\r","\n")
        expected=summary.strip().replace("\r\n","\n").replace("\r","\n")
        return "\n## Session summary\n\n"+expected+"\n" in "\n"+text
    except (OSError,ValueError,UnicodeError):return False


def supported_fact(answer):
    weights=re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:kg|kilograms?)\b",answer,re.I)
    if not weights or any(float(value)!=7 for value in weights):return False
    clauses=[c for c in re.split(r"[!?\n;]|\.(?!\d)",answer.lower()) if re.search(r"\b(?:kg|kilograms?)\b",c)]
    uncertainty=r"\b(?:not|no|unknown|perhaps|maybe|might|probably|unconfirmed|cannot)\b|n't"
    return bool(clauses) and all(not re.search(uncertainty,c) for c in clauses) and any(re.search(r"\b(?:limit|allowance|maximum|confirmed)\b",c) for c in clauses)


def unknown_shoe(answer):
    text=answer.lower().replace("’", "'").replace("*", "")
    clauses=[c.strip() for c in re.split(r"[.\n;]",text) if c.strip()]
    plan=r"^\s*i(?:'ll| will)\s+(?:check|search|look(?: up| through)?)\b"
    assertion=r"\d|[:,]|\b(?:is|are|was|were|equals|must|should|guess|think|believe|probably|likely)\b"
    clauses=[c for c in clauses if not (re.search(plan,c) and not re.search(assertion,c))]
    first=next((i for i,c in enumerate(clauses) if "shoe" in c),None)
    if first is None:return False
    unknown=r"(?:don.t know|do not know|don.t have|do not have|no (?:stored |recorded )?(?:information|evidence|note|record)|not (?:recorded|stored)|unknown)"
    numeric=r"\d|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b"
    contrary=r"\b(?:but|actually|however|instead)\b|\b(?:it|(?:your |the )?(?:shoe )?size)\s+(?:is|was|should be|must be)\s+(?!unknown\b|not\b|unrecorded\b|unavailable\b)"
    return all(re.search(unknown,c) and not re.search(numeric,c) and not re.search(contrary,c) for c in clauses[first:])



def _fixture_vault_id(vault):
    root = Path(vault).absolute()
    if not root.exists():
        return None
    observed = {}
    for directory in (root, *root.parents):
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("Fixture vault contains a linked or non-directory parent")
        observed[directory] = info
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Fixture vault marker contains duplicate JSON keys")
            result[key] = value
        return result
    values = set()
    for name in (".knowledgeos-vault.json", "knowledgeos.config.json"):
        path = root / name
        try:
            before = path.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or getattr(before, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                or before.st_size > 65536):
            raise ValueError("Fixture vault marker must be a bounded plain single-link file")
        def identity(info):
            return info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if identity(before) != identity(opened):
                raise ValueError("Fixture vault marker changed while opening")
            raw = stream.read(65537)
            after = os.fstat(stream.fileno())
            if (len(raw) > 65536 or identity(opened) != identity(after)
                    or opened.st_ctime_ns != after.st_ctime_ns):
                raise ValueError("Fixture vault marker changed while reading")
        current = path.lstat()
        if identity(current) != identity(before) or current.st_ctime_ns != before.st_ctime_ns:
            raise ValueError("Fixture vault marker changed after reading")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError("Fixture vault marker must be a JSON object")
        if "vault_id" in value:
            identifier = value["vault_id"]
            if not isinstance(identifier, str) or re.fullmatch(r"[0-9a-fA-F]{16,64}", identifier) is None:
                raise ValueError("Fixture vault marker needs a complete hexadecimal vault ID")
            values.add(identifier.lower())
    for directory, before in observed.items():
        after = directory.lstat()
        if (after.st_dev, after.st_ino, after.st_mode) != (before.st_dev, before.st_ino, before.st_mode):
            raise ValueError("Fixture vault directory changed during observation")
    if len(values) > 1:
        raise ValueError("Fixture vault markers disagree")
    return next(iter(values)) if values else None


def _bound_environment(server, vault, source_root=None):
    env = server.get("env", {})
    if not isinstance(env, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
        return False
    folded = [key.upper() for key in env]
    if len(folded) != len(set(folded)) or env.get("KNOWLEDGEOS_VAULT") != str(vault):
        return False
    if source_root is None:
        return "PYTHONPATH" not in folded
    return env.get("PYTHONPATH") == str(source_root) and "pythonpath" not in env


def source_binding(server,vault):
    try:
        if not isinstance(server, dict):
            return False
        identifier = _fixture_vault_id(vault)
        args = ["-P", "-m", "knowledgeos", "mcp"]
        if identifier is not None:
            args += ["--host-vault-id", identifier]
        args += ["--vault", str(vault)]
        if server.get("command") != str(sys.executable) or server.get("args") != args:
            return False
        if identifier is None:
            return server.get("env", {}).get("PYTHONPATH") == str(ROOT)
        return (Path(vault).is_absolute() and "cwd" not in server
                and server.get("required") is True and server.get("default_tools_approval_mode") == "approve"
                and _bound_environment(server, vault, ROOT))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def observe_chat(directory,label):
    text=(directory/(label+".stdout.jsonl")).read_text(encoding="utf-8")
    events=[json.loads(line) for line in text.splitlines() if line.strip()]
    messages=[e.get("item",{}).get("text","") for e in events if e.get("type")=="item.completed" and e.get("item",{}).get("type")=="agent_message"]
    wire=directory/(label+".wire.jsonl")
    records=rows(wire) if wire.exists() else []
    command=json.loads((directory/(label+".command.json")).read_text(encoding="utf-8"))
    return {"label":label,"exit_code":command["exit_code"],"events":events,"answer":"\n".join(messages),"wire":records,"calls":calls_from_wire(records),
            "evidence":[label+".stdout.jsonl",label+".wire.jsonl",label+".command.json"]}


class HostRun:
    def __init__(self,base,executable):
        self.directory=base/(time.strftime("%Y%m%d-%H%M%S-")+uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True)
        self.vault=self.directory/"vault"
        self.executable=executable
        self.env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE="1",PYTHONIOENCODING="utf-8",
                      KNOWLEDGEOS_STATE_DIR=str(self.directory/"gate-state"))
        for name in ("CODEX_APP_TOOLS_PIPE_PATH","CODEX_THREAD_ID","CODEX_SESSION_ID","CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
            self.env.pop(name,None)
        self.processes=[];self.cases=[]
        self.host={"name":"codex-cli","version":"unavailable","mode":"noninteractive genuine model sessions; source stdio MCP via transparent audit proxy"}
        self.sources=product_hashes()
        protected=[ROOT/"People/Self.md",ROOT/"knowledge_index.db",ROOT/".knowledgeos/autopilot.json",Path.home()/".codex/config.toml"]
        self.before={str(p):sha(p) for p in protected}
        self.protected=protected

    def command(self,label,argv,cwd=None,stdin="",timeout=120):
        process=subprocess.Popen(list(map(str,argv)),cwd=cwd or ROOT,env=self.env,stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
        tracked={"pid":process.pid,"role":label,"stopped":False};self.processes.append(tracked)
        started=time.monotonic()
        try:stdout,stderr=process.communicate(stdin,timeout=timeout)
        except BaseException:
            if os.name=="nt":
                subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True,timeout=20)
            else:process.kill()
            stdout,stderr=process.communicate(timeout=20)
            raise
        finally:
            tracked.update(stopped=process.poll() is not None,exit_code=process.returncode)
        (self.directory/(label+".stdout.jsonl")).write_text(stdout,encoding="utf-8")
        (self.directory/(label+".stderr.txt")).write_text(stderr,encoding="utf-8")
        (self.directory/(label+".command.json")).write_text(json.dumps({"command":list(map(str,argv)),"exit_code":process.returncode,"seconds":time.monotonic()-started},indent=2),encoding="utf-8")
        return process.returncode,stdout,stderr

    def check(self,identifier,condition,expected,observed,evidence):
        row={"id":identifier,"verdict":"PASS" if condition else "FAIL","expected":expected,"observed":observed,"evidence":evidence}
        self.cases.append(row);print(row["verdict"],identifier,flush=True)

    def initialize(self):
        code,text,error=self.command("init",[sys.executable,"-B","-P","-m","knowledgeos","init",self.vault,"--name","Synthetic host fixture","--non-interactive"])
        if code:raise RuntimeError("Fixture initialization failed: "+error)
        self.identity=sha(self.vault/"People/Self.md")
        code,_,error=self.command("doctor",[sys.executable,"-B","-P","-m","knowledgeos","doctor","--vault",self.vault])
        if code:raise RuntimeError("Fixture doctor failed: "+error)
        code,_,error=self.command("setup",[sys.executable,"-B","-P","-m","knowledgeos","setup-host","--host","codex","--vault",self.vault,"--write"])
        if code:raise RuntimeError("Native Codex setup failed: "+error)
        import tomllib
        path=self.vault/".codex/config.toml";self.original_config=path.read_bytes()
        config=tomllib.loads(self.original_config.decode("utf-8"));self.server=config["mcp_servers"]["knowledgeos"]
        if not source_binding(self.server,self.vault):
            raise RuntimeError("Generated launcher is not bound to this source checkout; verify installed artifacts separately")
        (self.directory/"generated-config.toml").write_bytes(self.original_config)
        code,version,error=self.command("host-version",[self.executable,"--version"])
        if code:raise RuntimeError("Codex version failed: "+error)
        self.host["version"]=version.strip()

    def chat(self,label,prompt):
        from knowledgeos.host_setup import render_codex_config
        server=dict(self.server);server["env"]={**server.get("env",{}),"KNOWLEDGEOS_STATE_DIR":str(self.directory/"gate-state"),"PYTHONDONTWRITEBYTECODE":"1"}
        server["command"]=sys.executable
        server["args"]=["-B","-P",str(Path(__file__).resolve()),"--proxy",str(self.directory/(label+".wire.jsonl")),"--",self.server["command"],*self.server.get("args",[])]
        # Each concurrent conversation gets its own copied project configuration.
        # The actual server command and vault are unchanged behind the wire proxy.
        project=self.directory/(label+"-project");project.mkdir()
        (project/"AGENTS.md").write_bytes((self.vault/"AGENTS.md").read_bytes())
        (project/".twinaatma-host-profile").write_text("Synthetic host discovery profile.\n",encoding="utf-8")
        (project/".codex").mkdir()
        (project/".codex/config.toml").write_text(render_codex_config({"mcp_servers":{"knowledgeos":server}}),encoding="utf-8")
        args=[self.executable,"--disable","apps","--disable","plugins","--disable","remote_plugin","exec","--strict-config","--ignore-user-config","--ephemeral","--skip-git-repo-check","--sandbox","read-only","--json","--color","never","-C",str(project),
              "-c",'project_root_markers=[".twinaatma-host-profile"]',"-c",'projects={'+json.dumps(str(project))+'={trust_level="trusted"}}']
        # Retain the configured model without inheriting unrelated server settings.
        user_config=Path.home()/".codex/config.toml"
        if user_config.is_file():
            import tomllib
            model=tomllib.loads(user_config.read_text(encoding="utf-8")).get("model")
            if model:args += ["-m",model]
        code,text,error=self.command(label,args,cwd=project,stdin=prompt,timeout=240)
        return observe_chat(self.directory,label)

    def drive(self):
        first=self.chat("capture","For Project Seaglass, the cabin luggage allowance is 7 kg. Please remember that for our packing decisions.")
        if first["exit_code"]:raise RuntimeError("First genuine host chat failed")
        if not first["calls"] or first["calls"][0]["name"]!="memory_session_start" or not first["calls"][0]["ok"]:
            self.check("host.discovery",False,"Actual host loads native memory configuration",first["answer"],first["evidence"])
            self.check("host.first_memory_call",False,"First memory operation is successful startup",first["calls"],first["evidence"])
            raise RuntimeError("No successful startup through the real host; later model calls skipped")
        with ThreadPoolExecutor(max_workers=2) as pool:
            recall_future=pool.submit(self.chat,"recall","What is my cabin luggage allowance for Project Seaglass? State the limit and cite the stored note path. Also, what is my shoe size? If you lack evidence, say you do not know.")
            other_future=pool.submit(self.chat,"parallel","Give me one practical packing tip for Project Seaglass based on what you remember. Cite the stored note you used.")
            second,third=recall_future.result(),other_future.result()
        self.grade([first,second,third])

    def grade(self,chats):
        first,second,third=chats
        evidence=sum((c["evidence"] for c in chats),[])
        methods=[r.get("message",{}).get("method") for c in chats for r in c["wire"] if r.get("kind")=="request"]
        self.check("host.discovery",all(c["exit_code"]==0 for c in chats) and "tools/list" in methods,"Actual host discovers the memory server and completes all chats",{"methods":methods},evidence)
        self.check("host.first_memory_call",all(c["calls"] and c["calls"][0]["name"]=="memory_session_start" and c["calls"][0]["ok"] for c in chats),"First memory operation is successful startup in every genuine chat",[[call["name"] for call in c["calls"]] for c in chats],evidence)
        captures=[c for c in first["calls"] if c["name"]=="memory_capture" and c["ok"]]
        saved=[c["payload"].get("path","") for c in captures]
        persisted=any(path and supported_fact((self.vault/path).read_text(encoding="utf-8")) for path in saved)
        self.check("host.capture_from_chat",persisted,"Normal conversational fact is durably captured without a save command",saved,first["evidence"])
        retrieved=[]
        for call in second["calls"]:
            payload=call["payload"]
            if call["name"]=="memory_session_start":hits=payload.get("context",{}).get("relevant",{}).get("ranked",[])
            elif call["name"]=="memory_search":hits=payload.get("ranked",[])
            elif call["name"]=="memory_get_note":hits=[payload]
            else:continue
            retrieved.extend(hit.get("path") for hit in hits if isinstance(hit,dict))
        grounded=[path for path in saved if path in retrieved and path in second["answer"]]
        self.check("host.recall_after_restart",bool(grounded) and supported_fact(second["answer"]),"A new host process retrieves the saved fact and answers with its source",{"retrieved":retrieved,"answer":second["answer"]},second["evidence"])
        self.check("host.grounded_answer",bool(grounded) and persisted and supported_fact(second["answer"]),"The factual answer matches stored bytes and cites a retrieved source",{"cited_saved_paths":grounded,"answer":second["answer"]},second["evidence"])
        unknown=unknown_shoe(second["answer"])
        self.check("host.unknown_abstains",unknown and bool(re.search(r"shoe",second["answer"],re.I)),"Unsupported shoe size remains explicitly unknown",second["answer"],second["evidence"])
        pairs=[session_pair(c["calls"]) for c in chats]
        state=json.loads((self.vault/".knowledgeos/autopilot.json").read_text(encoding="utf-8"))
        ids=[p[0] for p in pairs if p]
        independent=len(ids)==3 and len(set(ids))==3 and all(state.get("sessions",{}).get(sid,{}).get("status")=="ended" for sid in ids)
        self.check("host.session_id_propagated",independent,"Each real chat passes its own returned ID to wrap and remains separate",{"session_ids":ids,"state":state},evidence)
        wraps=[p[1] for p in pairs if p]
        summaries=[wrap["payload"].get("captured",{}) for wrap in wraps]
        valid_summaries=len(wraps)==3 and all(summary_saved(self.vault,receipt,wrap["arguments"].get("summary")) for wrap,receipt in zip(wraps,summaries))
        if valid_summaries:
            paths=[receipt["path"].casefold() if os.name=="nt" else receipt["path"] for receipt in summaries]
            valid_summaries=len(set(paths))==3
        self.check("host.summary_persisted",valid_summaries,"Every successful host wrap persists its submitted summary in a distinct plain Inbox note",summaries,evidence)
        chores=any(re.search(r"(?:run|execute|rebuild)\s+(?:`?(?:twinaatma|python)|(?:the |your )?index)",c["answer"],re.I) for c in chats)
        shell=any(e.get("item",{}).get("type")=="command_execution" for c in chats for e in c["events"])
        self.check("host.no_user_ops",not chores and not shell,"Normal chats need no user index/schema/script operations or shell fallback",{"answers":[c["answer"] for c in chats],"shell_fallback":shell},evidence)
        self.check("host.identity_unchanged",sha(self.vault/"People/Self.md")==self.identity,"Conversational captures and unknowns leave identity bytes unchanged",{"before":self.identity,"after":sha(self.vault/"People/Self.md")},evidence)

    def finish(self,error=None):
        if not getattr(self,"replayed_from",None):
            self.processes.extend(collect_shutdown(self.directory.glob("*.wire.jsonl")))
        after={str(p):sha(p) for p in self.protected}
        transcripts={p.name:sha(p) for p in self.directory.iterdir() if p.is_file() and p.name!="report.json"}
        report={"schema_version":1,"producer":PRODUCER,"producer_sha256":sha(__file__),"host":self.host,"product_hashes":self.sources,
                "cases":self.cases,"processes":self.processes,"transcript_files":transcripts,"isolation":{"before":self.before,"after":after},
                "product_unchanged":self.sources==product_hashes(),"error":error,
                "server_source_bound":source_binding(getattr(self,"server",{}),self.vault),
                "replayed_from":getattr(self,"replayed_from",None),
                "limits":["Source-backed Codex CLI exec, not desktop UI, installed package, all-host or human approval acceptance.","Transparent wire proxy launches the exact generated server command; task profiles share a synthetic vault.","One capture plus two concurrent new host processes; no week-long quality, correction or efficiency acceptance claim."]}
        report["verdict"]="PASS" if not error and self.cases and all(c["verdict"]=="PASS" for c in self.cases) and self.before==after and report["product_unchanged"] and all(p["stopped"] for p in self.processes) else "FAIL"
        path=self.directory/"report.json"
        path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        from acceptance import snapshot
        try:
            coverage=snapshot([], [path])
            (self.directory/"acceptance.json").write_text(json.dumps(coverage,indent=2),encoding="utf-8")
            print(f"Run-only ideal coverage: {coverage['counts']['PASS']}/54; unresolved {coverage['unresolved_percent']:.2f}% (combine reports for progress)")
        except ValueError as exc:
            coverage=snapshot([], [])
            coverage["unusable_host_report"]=str(exc)
            (self.directory/"acceptance.json").write_text(json.dumps(coverage,indent=2),encoding="utf-8")
            print("Run-only ideal coverage: 0/54; host execution evidence unusable")
            (self.directory/"acceptance-error.txt").write_text(str(exc),encoding="utf-8")
            report["acceptance_error"]=str(exc)
            report["verdict"]="FAIL"
            path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        print("Evidence:",self.directory,flush=True)
        return 0 if report["verdict"]=="PASS" else 1


def main():
    if len(sys.argv)>1 and sys.argv[1]=="--proxy":
        separator=sys.argv.index("--")
        return proxy(Path(sys.argv[2]),sys.argv[separator+1:])
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--codex",default="codex")
    parser.add_argument("--replay",type=Path,help="Regrade unchanged retained genuine host evidence without new model calls")
    args=parser.parse_args()
    base=args.output.resolve()
    relative=base.relative_to((ROOT/"work/gc-artifacts").resolve())
    if ".knowledgeos" not in relative.parts:parser.error("Output must contain .knowledgeos beneath work/gc-artifacts")
    if sys.version_info<(3,11):parser.error("Host driver requires Python 3.11+")
    run=HostRun(base,args.codex)
    error=None
    try:
        if args.replay:
            import tomllib
            original=args.replay.resolve();old=json.loads(original.read_text(encoding="utf-8"))
            if old.get("producer")!=PRODUCER or old.get("product_hashes")!=run.sources or not old.get("product_unchanged"):
                raise ValueError("Retained host evidence does not bind this current product")
            if old.get("isolation",{}).get("before")!=old.get("isolation",{}).get("after") or old["isolation"]["before"]!=run.before:
                raise ValueError("Retained isolation proof does not match current sentinels")
            if not old.get("processes") or any(p.get("stopped") is not True for p in old["processes"]):
                raise ValueError("Retained processes lack shutdown proof")
            for name,digest in old.get("transcript_files",{}).items():
                path=original.parent/name
                if Path(name).name!=name or path.is_symlink() or sha(path)!=digest:
                    raise ValueError("Retained transcript missing or changed: "+name)
                shutil.copy2(path,run.directory/name)
            run.vault=original.parent/"vault"
            run.server=tomllib.loads((run.directory/"generated-config.toml").read_text(encoding="utf-8"))["mcp_servers"]["knowledgeos"]
            if not source_binding(run.server,run.vault):raise ValueError("Retained execution was not bound to current source")
            identity=next(c for c in old["cases"] if c["id"]=="host.identity_unchanged")
            run.identity=identity["observed"]["before"]
            run.host={**old["host"],"mode":old["host"]["mode"]+"; retained observations regraded, no new live trial"}
            run.processes=old["processes"]
            run.replayed_from={"report":str(original),"sha256":sha(original),"original_producer_sha256":old.get("producer_sha256")}
            run.grade([observe_chat(run.directory,name) for name in ["capture","recall","parallel"]])
        else:
            run.initialize();run.drive()
    except Exception as exc:error=f"{type(exc).__name__}: {exc}";print(error,file=sys.stderr)
    return run.finish(error)


if __name__=="__main__":raise SystemExit(main())
