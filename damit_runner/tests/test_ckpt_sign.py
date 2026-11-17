"""DamIT Runner 0.6.0: ANUGA checkpoints are signed, and only a checkpoint this user's own runs
signed is loaded (core/ckpt_sign.py and core/anuga_worker.py, ported from DamSafety Runner 3.20.3).

A checkpoint is a pickle of the domain, and loading a pickle runs the code in it. The worker
writes <checkpoint>.sig (HMAC-SHA256 under a key in the user's settings folder) when it saves
one, and checks it before loading. NDBREACH_ANUGA_RESUME_TRUST=1 loads the user's own unsigned
checkpoint. The proof that nothing is unpickled: a planted pickle that would write a marker file.

These are DamSafety's tests of the signing module and of the worker's load gate. Its tests of a
whole interrupted and resumed run need DamSafety's stand-in ANUGA and stay there; the two files
they exercise are held to DamSafety's by the parity gate.

The key is a temporary one (NDBREACH_CKPT_KEY_FILE): the user's own key is never read or made."""
import atexit
import json
import os
import pickle
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.core import ckpt_sign as CS  # noqa: E402

try:
    from damit_runner.core import anuga_worker as AW  # noqa: E402
except ImportError:                                   # no numpy here: the gate test is skipped
    AW = None

_KEY_DIR = tempfile.mkdtemp(prefix="damit_test_key_")
atexit.register(shutil.rmtree, _KEY_DIR, True)
_OWN_KEY = {CS.KEY_FILE_ENV: os.path.join(_KEY_DIR, "anuga_checkpoint.key")}

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn



class _Env:
    """Set some environment variables (None = unset) for a block, then restore."""

    def __init__(self, **kw):
        self.kw = dict(_OWN_KEY, **kw)

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.kw}
        for k, v in self.kw.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def _load_checkpoint_file(domain_name="domain", checkpoint_dir=".", time=None):
    """ANUGA's loader, reduced to what it does to the file: unpickle it."""
    p = os.path.join(checkpoint_dir, domain_name) + "_" + str(float(time)) + ".pickle"
    with open(p, "rb") as f:
        return pickle.load(f)


def _file(d, name="anuga_breach_600.0.pickle", data=b"domain bytes"):
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


@test
def ckpt_sign_a_signed_file_verifies_and_any_change_or_other_key_does_not():
    d = tempfile.mkdtemp()
    try:
        key = os.path.join(d, "keys", "k.key")
        env = {CS.KEY_FILE_ENV: key}
        p = _file(d)
        assert CS.verify(p, env) == (False, CS.verify(p, env)[1])
        assert "no signature" in CS.verify(p, env)[1]
        assert not os.path.exists(key)                 # checking never makes a key
        assert CS.sign(p, env) == ""
        sig = json.load(open(CS.sig_path(p)))
        assert sig["alg"] == "HMAC-SHA256" and len(sig["mac"]) == 64 and sig["size"] == 12
        assert CS.verify(p, env) == (True, "")
        # the key: 32 random bytes as hex, never the same twice, for this user only
        raw = open(key).read().strip()
        assert len(bytes.fromhex(raw)) == 32
        if os.name == "posix":
            assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
            assert stat.S_IMODE(os.stat(os.path.dirname(key)).st_mode) == 0o700
        # one byte changed, same size
        with open(p, "r+b") as f:
            f.write(b"D")
        ok, why = CS.verify(p, env)
        assert not ok and "changed since it was signed" in why, why
        # a longer file
        _file(d, data=b"domain bytes and more")
        ok, why = CS.verify(p, env)
        assert not ok and why == "the file has changed since it was signed", why
        # signed with another user's key
        _file(d)
        other = {CS.KEY_FILE_ENV: os.path.join(d, "other.key")}
        assert CS.sign(p, other) == "" and CS.verify(p, other) == (True, "")
        ok, why = CS.verify(p, env)
        assert not ok and "another user or computer" in why, why
        assert open(key).read().strip() != open(other[CS.KEY_FILE_ENV]).read().strip()
        # a user with no key at all, a signature that is not ours, one that is not JSON
        ok, why = CS.verify(p, {CS.KEY_FILE_ENV: os.path.join(d, "none.key")})
        assert not ok and "has no checkpoint key" in why, why
        with open(CS.sig_path(p), "w") as f:
            json.dump({"alg": "none", "mac": "00"}, f)
        assert "not one the Runner writes" in CS.verify(p, env)[1]
        with open(CS.sig_path(p), "w") as f:
            f.write("not json")
        assert "cannot be read" in CS.verify(p, env)[1]
        CS.remove_sig(p)
        CS.remove_sig(p)                               # twice is fine
        assert not os.path.exists(CS.sig_path(p))
    finally:
        shutil.rmtree(d)


@test
def ckpt_sign_a_damaged_key_file_is_never_replaced_and_signs_nothing():
    d = tempfile.mkdtemp()
    try:
        key = os.path.join(d, "k.key")
        with open(key, "w") as f:
            f.write("abcd")                            # too short to be a key
        env = {CS.KEY_FILE_ENV: key}
        p = _file(d)
        err = CS.sign(p, env)
        assert "no signing key" in err and not os.path.exists(CS.sig_path(p)), err
        assert open(key).read() == "abcd"
        assert CS.load_key(True, {CS.KEY_FILE_ENV: os.path.join(d, "no", "such", "k")})
    finally:
        shutil.rmtree(d)


@test
def ckpt_sign_settings_folder_is_the_users_own_on_each_system():
    home = os.path.expanduser("~")
    assert CS.settings_dir({"APPDATA": r"C:\Users\n\AppData\Roaming"}, "win32") == \
        os.path.join(r"C:\Users\n\AppData\Roaming", "DamIT")
    assert CS.settings_dir({}, "darwin") == os.path.join(
        home, "Library", "Application Support", "DamIT")
    assert CS.settings_dir({"XDG_CONFIG_HOME": "/x"}, "linux") == os.path.join("/x", "DamIT")
    assert CS.settings_dir({}, "linux") == os.path.join(home, ".config", "DamIT")
    assert CS.key_path({CS.KEY_FILE_ENV: "/k"}) == "/k"
    assert not CS.trusted({}) and CS.trusted({CS.TRUST_ENV: "1"}) and \
        not CS.trusted({CS.TRUST_ENV: "0"})


class _Planted:
    """Unpickling this would create the marker file."""

    def __init__(self, marker):
        self.marker = marker

    def __reduce__(self):
        return (open, (self.marker, "w"))


@test
def ckpt_sign_the_signature_is_the_only_gate_before_the_pickle_is_loaded():
    """The control works both ways: the planted pickle runs when the user says to trust it,
    and only then. (So the test above is not passing because the loader ignores the file.)"""
    import types
    if AW is None:
        raise unittest.SkipTest("the ANUGA worker needs numpy")
    d = tempfile.mkdtemp()
    try:
        marker = os.path.join(d, "RAN")
        p = AW.checkpoint_path(d, 600.0)
        with open(p, "wb") as f:
            pickle.dump(_Planted(marker), f)
        anuga = types.SimpleNamespace(load_checkpoint_file=_load_checkpoint_file)
        meta = {"times": [600.0]}
        refused = []
        with _Env(**{CS.TRUST_ENV: None}):
            dom, why = AW.load_latest_checkpoint(anuga, d, meta, refused)
        assert dom is None and refused == [p] and "was not loaded" in why, why
        assert not os.path.exists(marker)
        import contextlib
        import io
        out = io.StringIO()
        with _Env(**{CS.TRUST_ENV: "1"}), contextlib.redirect_stdout(out):
            dom, t = AW.load_latest_checkpoint(anuga, d, meta, [])
        if dom is not None:
            dom.close()
        assert os.path.exists(marker) and t == 600.0
        assert "does not verify" in out.getvalue() and CS.TRUST_ENV + "=1" in out.getvalue()
    finally:
        shutil.rmtree(d)


def _with_own_key(fn):
    with _Env():
        return fn()


class Ported(unittest.TestCase):
    """The DamSafety tests of this module, each as one unittest case."""


for _fn in TESTS:
    setattr(Ported, "test_" + _fn.__name__, (lambda fn: lambda self: _with_own_key(fn))(_fn))


if __name__ == "__main__":
    unittest.main()
