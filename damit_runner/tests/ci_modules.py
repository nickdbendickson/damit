"""List damit_runner test modules for CI.

.github/workflows/damit_runner.yml does not name modules. This script lists
test_*.py, subtracts CI_EXCLUDE.txt, and puts CI_SCIPY.txt in the step that
runs after scipy is installed. Every test file is in exactly one place: the
numpy tier, the scipy tier, or the exclude file. A tier that would launch
nothing is fatal, because `python -m unittest` exits 0 when it collects nothing.

A line in either list is `stem  # reason`. A missing reason, a stem with no
file, or a stem in both lists fails the job.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXCLUDE_NAME = "CI_EXCLUDE.txt"
SCIPY_NAME = "CI_SCIPY.txt"


def test_stems(tests_dir):
    """test_*.py stems in `tests_dir`, sorted. Subdirectories are not packages."""
    out = []
    for name in os.listdir(tests_dir):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        if os.path.isfile(os.path.join(tests_dir, name)):
            out.append(name[:-3])
    return sorted(out)


def _stem_ok(stem):
    rest = stem[len("test_"):]
    return stem.startswith("test_") and rest != "" and rest.replace("_", "").isalnum()


def parse_entries(path):
    """(stems in file order, errors). Blank lines and full-line comments are ignored."""
    errors = []
    stems = []
    if not os.path.isfile(path):
        return [], ["{} is missing".format(path)]
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    seen = set()
    for n, line in enumerate(lines, 1):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "#" not in line:
            errors.append("{}:{} has no reason (write `stem  # why`)".format(path, n))
            stem, reason = raw.split()[0], ""
        else:
            left, reason = line.split("#", 1)
            stem, reason = left.strip(), reason.strip()
            if not reason:
                errors.append("{}:{} {} has no reason".format(path, n, stem or "(blank)"))
        if not _stem_ok(stem):
            errors.append("{}:{} {!r} is not a test module stem".format(path, n, stem))
            continue
        if stem in seen:
            errors.append("{}:{} {} is listed twice".format(path, n, stem))
            continue
        seen.add(stem)
        stems.append(stem)
    return stems, errors


def classify(tests_dir, exclude_path=None, scipy_path=None):
    """numpy / scipy / excluded stems, plus a list of fatal errors (possibly empty)."""
    exclude_path = exclude_path or os.path.join(tests_dir, EXCLUDE_NAME)
    scipy_path = scipy_path or os.path.join(tests_dir, SCIPY_NAME)
    errors = []
    excluded, err_x = parse_entries(exclude_path)
    scipy, err_s = parse_entries(scipy_path)
    errors.extend(err_x)
    errors.extend(err_s)
    files = test_stems(tests_dir)
    have = set(files)
    for stem in excluded:
        if stem not in have:
            errors.append("CI_EXCLUDE.txt lists {}, which is not a test_*.py".format(stem))
    for stem in scipy:
        if stem not in have:
            errors.append("CI_SCIPY.txt lists {}, which is not a test_*.py".format(stem))
    for stem in sorted(set(excluded) & set(scipy)):
        errors.append("{} is in both CI_EXCLUDE.txt and CI_SCIPY.txt".format(stem))
    skip = set(excluded) | set(scipy)
    numpy = [stem for stem in files if stem not in skip]
    placed = set(numpy) | set(scipy) | set(excluded)
    for stem in sorted(have - placed):
        errors.append("{} is neither run nor excluded".format(stem))
    if not numpy:
        errors.append("numpy tier is empty")
    if not scipy:
        errors.append("scipy tier is empty")
    return {"numpy": numpy, "scipy": list(scipy), "excluded": list(excluded), "errors": errors}


def main(argv):
    tier = "numpy"
    if "--tier" in argv:
        i = argv.index("--tier")
        if i + 1 >= len(argv) or argv[i + 1] not in ("numpy", "scipy"):
            print("FATAL: --tier must be numpy or scipy", file=sys.stderr)
            return 1
        tier = argv[i + 1]
    result = classify(HERE)
    if result["errors"]:
        for err in result["errors"]:
            print("FATAL: " + err, file=sys.stderr)
        return 1
    names = result[tier]
    if not names:
        print("FATAL: {} tier is empty".format(tier), file=sys.stderr)
        return 1
    sys.stdout.write(" ".join("damit_runner.tests." + name for name in names))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
