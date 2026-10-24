"""One binding for the frozen host batch.

A single pin file (`host-freeze-pin.json`, next to this module) names the freeze
folder and the hash of its seal. The seal lists the hash of the product freeze and of
every support file. Nothing else in the host graders names a freeze, so a new freeze
needs exactly one new pin. Counts come from the freeze file and the live tree.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
PIN_PATH = SCRIPTS / "host-freeze-pin.json"
PIN_SCHEMA = "verify-twinaatma.host-freeze-pin/v1"
SEAL_SCHEMA = "verify-twinaatma.host-batch-seal/v1"
SEAL_NAME = "batch-seal.json"
FREEZE_NAME = "product-freeze.json"
FREEZE_SCHEMA = "twinaatma.C-product-freeze/v1"
RUBRIC_SHA256 = "744e4913702f6fdf344f233491f019737aa1a2d5adf65edf7ab1c48fce98aa91"
FREEZE_KEYS = {
    "schema", "source_revision", "frozen_at_ns", "product", "fixed_target", "rubric_sha256",
    "integration_receipt_sha256", "historical_baseline", "historical_baseline_sha256",
    "root_Self_sha256", "new_live_model_authorization",
}
SUPPORT_NAMES = (
    "advanced_host.py", "controls.py", "expectations.json", "prepared.json",
    "private/input.json", "outbound-payload-review.json",
)
UNITS = ("installed-wheel", "installed-binary", "advanced-source")
HOST_KEYS = {"cli", "cli_sha256", "version", "configured_model"}
FREEZE_FOLDER = re.compile(r"work/gc-artifacts/\.knowledgeos/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
ROOT_INPUTS = ("AGENTS.md", "README.md", "pyproject.toml", "setup.py", "MANIFEST.in", "LICENSE",
               "knowledgeos.config.example.json", "mcp.cursor.example.json")
INPUT_FOLDERS = ("knowledgeos", "scripts", "Templates", ".cursor/hooks")


class BindingError(ValueError):
    """The pinned freeze, its seal, or the product no longer agree."""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BindingError("Duplicate JSON key in a pinned binding file")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique)


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def plain_file(path, root=None):
    """Return a plain single-link file whose whole path below `root` has no link."""
    root = Path(root or ROOT).absolute()
    path = Path(path).absolute()
    if ".." in path.parts or ".." in root.parts:
        raise BindingError("Pinned file contains a parent traversal")
    try:
        path.relative_to(root)
    except ValueError as error:
        raise BindingError("Pinned file is outside the checkout: " + path.name) from error
    cursor = path
    while True:
        info = cursor.lstat()
        if _linked(info):
            raise BindingError("Pinned file uses a linked path: " + path.name)
        if cursor == path:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise BindingError("Pinned file is not a plain single-link file: " + path.name)
        elif not stat.S_ISDIR(info.st_mode):
            raise BindingError("Pinned file parent is not a directory: " + path.name)
        if cursor == root:
            break
        cursor = cursor.parent
    return path


def toolkit_inputs(root=None):
    """Every file the product freeze covers, hashed from the live tree."""
    root = Path(root or ROOT).absolute()
    paths = []
    for folder in INPUT_FOLDERS:
        for path in (root / folder).rglob("*"):
            if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            info = path.lstat()
            if _linked(info):
                raise BindingError("Toolkit input is linked: " + path.name)
            if not stat.S_ISDIR(info.st_mode):
                paths.append(path)
    paths.extend(root / name for name in ROOT_INPUTS)
    return {path.relative_to(root).as_posix(): sha(plain_file(path, root)) for path in sorted(set(paths))}


def freeze_product(freeze_path):
    """Return the product dictionary of a freeze, after a strict schema check."""
    data = read_json(freeze_path)
    product = data.get("product") if isinstance(data, dict) else None
    if (not isinstance(data, dict) or set(data) != FREEZE_KEYS or data["schema"] != FREEZE_SCHEMA
            or not isinstance(product, dict) or not product
            or any(not isinstance(name, str) or not isinstance(digest, str) or not HEX.fullmatch(digest)
                   for name, digest in product.items())
            or type(data["fixed_target"]) is not int or data["fixed_target"] != 54
            or data["rubric_sha256"] != RUBRIC_SHA256
            or data["new_live_model_authorization"] is not False
            or type(data["frozen_at_ns"]) is not int or data["frozen_at_ns"] <= 0):
        raise BindingError("Product freeze does not match the fixed schema")
    return product


def check_product(product, root=None):
    """Refuse a product that differs from the live tree in any file or in the file set."""
    live = toolkit_inputs(root)
    if set(product) != set(live):
        raise BindingError("Frozen source inputs differ from the live tree: file set changed")
    if any(live[name] != digest for name, digest in product.items()):
        raise BindingError("Frozen source inputs differ from the live tree: product changed")
    return len(product)


def load_pin(pin_path=None, root=None):
    root = Path(root or ROOT)
    pin_path = Path(pin_path or PIN_PATH)
    try:
        pin = read_json(plain_file(pin_path, pin_path.parent))
    except FileNotFoundError as error:
        raise BindingError("No host freeze is pinned: run host_batch.py prepare") from error
    host = pin.get("host") if isinstance(pin, dict) else None
    if (not isinstance(pin, dict) or set(pin) != {"schema", "freeze_dir", "seal_sha256", "host"}
            or pin["schema"] != PIN_SCHEMA or not isinstance(pin["freeze_dir"], str)
            or not FREEZE_FOLDER.fullmatch(pin["freeze_dir"])
            or not isinstance(pin["seal_sha256"], str) or not HEX.fullmatch(pin["seal_sha256"])
            or not isinstance(host, dict) or set(host) != HOST_KEYS
            or any(not isinstance(value, str) or not value for value in host.values())
            or not HEX.fullmatch(host["cli_sha256"])):
        raise BindingError("Host freeze pin is malformed")
    return pin


class Binding:
    """The checked answer to: which freeze, which seal, which support hashes."""

    def __init__(self, root, base, pin_path, pin, seal, freeze_sha256, product):
        self.root = Path(root)
        self.base = base
        self.freeze = base / FREEZE_NAME
        self.seal = base / SEAL_NAME
        self.pin_path = Path(pin_path)
        self.pin_sha256 = sha(pin_path)
        self.seal_sha256 = pin["seal_sha256"]
        self.frozen_sha256 = freeze_sha256
        self.support = dict(seal["support"])
        self.host = dict(pin["host"])
        self.product = product
        self.source_input_count = len(product)

    @property
    def inventory_sha256(self):
        return self.support["outbound-payload-review.json"]

    @property
    def client_version(self):
        return self.host["version"].rpartition(" ")[2]


def load_binding(root=None, pin_path=None):
    """Resolve and check the pin, the seal and the product freeze. Never the live product."""
    try:
        return _load_binding(root, pin_path)
    except FileNotFoundError as error:
        raise BindingError("A pinned freeze file is missing: " + Path(error.filename or "?").name) from error


def _load_binding(root, pin_path):
    root = Path(root or ROOT)
    pin_path = Path(pin_path or PIN_PATH)
    pin = load_pin(pin_path, root)
    base = root.joinpath(*pin["freeze_dir"].split("/"))
    seal_path = plain_file(base / SEAL_NAME, root)
    if sha(seal_path) != pin["seal_sha256"]:
        raise BindingError("The pinned freeze seal changed or was swapped")
    seal = read_json(seal_path)
    support = seal.get("support") if isinstance(seal, dict) else None
    if (not isinstance(seal, dict) or set(seal) != {"schema", "product_freeze_sha256", "source_input_count", "support"}
            or seal["schema"] != SEAL_SCHEMA or not isinstance(seal["product_freeze_sha256"], str)
            or not HEX.fullmatch(seal["product_freeze_sha256"])
            or type(seal["source_input_count"]) is not int or seal["source_input_count"] <= 0
            or not isinstance(support, dict) or set(support) != set(SUPPORT_NAMES)
            or any(not isinstance(value, str) or not HEX.fullmatch(value) for value in support.values())):
        raise BindingError("The freeze seal is malformed")
    freeze_path = plain_file(base / FREEZE_NAME, root)
    if sha(freeze_path) != seal["product_freeze_sha256"]:
        raise BindingError("The product freeze changed or was swapped after sealing")
    product = freeze_product(freeze_path)
    if len(product) != seal["source_input_count"]:
        raise BindingError("The sealed source input count differs from the freeze file")
    return Binding(root, base, pin_path, pin, seal, seal["product_freeze_sha256"], product)


def check_support(binding):
    """Every support file must still have its sealed hash."""
    current = {name: sha(plain_file(binding.base / name, binding.root)) for name in SUPPORT_NAMES}
    if current != binding.support:
        raise BindingError("Staged producer, controls, expectations or payload inventory changed after sealing")


def authorization_problem(authorization, frozen_sha256, inventory_sha256, units=UNITS, maximum=None, model=None):
    """Return why an authorization record does not bind this freeze, else None."""
    if not isinstance(authorization, dict) or authorization.get("status") != "approved":
        return "Authorization is not an approved record"
    if authorization.get("product_freeze_sha256") != frozen_sha256:
        return "Authorization is bound to a different product freeze"
    if authorization.get("payload_inventory_sha256") != inventory_sha256:
        return "Authorization is bound to a different payload inventory"
    allowed = authorization.get("allowed_units")
    if not isinstance(allowed, dict) or any(type(allowed.get(unit)) is not int or allowed[unit] != 3 for unit in units):
        return "Authorization does not allow exactly three conversations per required unit"
    if maximum is not None and (type(authorization.get("maximum_model_conversations")) is not int
                                or authorization["maximum_model_conversations"] != maximum):
        return "Authorization maximum differs from the batch"
    reply = authorization.get("direct_user_reply")
    if not isinstance(reply, str) or not reply.strip():
        return "Authorization lacks the direct human reply"
    if model is not None and (authorization.get("single_use") is not True
                              or authorization.get("automatic_retries") is not False
                              or authorization.get("model") != model
                              or type(authorization.get("recorded_ns")) is not int
                              or authorization["recorded_ns"] <= 0):
        return "Authorization must be single use, without retries, for the pinned model, with a recording time"
    return None


def write_pin(pin_path, freeze_dir, seal_sha256, host):
    pin = {"schema": PIN_SCHEMA, "freeze_dir": freeze_dir, "seal_sha256": seal_sha256, "host": host}
    path = Path(pin_path)
    text = json.dumps(pin, indent=2) + "\n"
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(text.replace("\n", "\r\n"))
    return pin
