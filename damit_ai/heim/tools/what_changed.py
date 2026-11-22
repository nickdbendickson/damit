#!/usr/bin/env python3
# what_changed.py v1.0 - write the knowledge pack's WHAT-CHANGED.md from the repositories' history.
#
#   python3 what_changed.py --repo ~/damit --repo ~/DWR_Plugins              # last 45 days
#   python3 what_changed.py --repo ~/damit --days 90 --out /tmp/WHAT-CHANGED.md
#
# The curated pages of the knowledge pack are written by hand and fall behind: on 2026-11-22 they
# had not one word about Boann's six engines, merged over the four days before. This page is
# generated, so it is never behind the checkout it was made from: one line per commit on the
# default branch's first-parent line (merged pull requests and direct commits), newest first,
# under the date and the repository. Heim indexes it with the rest of the pack, and heim-doctor
# says when it is old. Plain Python and git; no model, nothing leaves the machine.
import argparse, datetime, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(os.path.dirname(HERE), "knowledge", "WHAT-CHANGED.md")
MAX_BYTES = 240 * 1024          # rag_index skips text over 256 KB
STAMP = "Generated "            # first words of line 3; heim-doctor reads the date after them


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, check=True).stdout


def commits(repo, days):
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    out = git(repo, "log", "--first-parent", "--since=" + since, "--date=short",
              "--format=%h\x1f%ad\x1f%s\x1f%b\x1e", "HEAD")
    rows = []
    for rec in out.split("\x1e"):
        parts = rec.strip("\n").split("\x1f", 3)
        if len(parts) != 4:
            continue
        sha, day, subject, body = parts
        if subject.startswith("Merge pull request "):
            # GitHub's merge commit: the pull request's own title is the body's first line
            title = next((b.strip() for b in body.splitlines() if b.strip()), "")
            num = subject.split()[3] if len(subject.split()) > 3 else ""
            subject = ("%s (%s)" % (title, num)) if title else subject
        rows.append((sha, day, subject))
    return rows


def build(repos, days, today=None):
    today = today or datetime.date.today().isoformat()
    heads, by_day = [], {}
    for name, path in repos:
        heads.append("%s %s" % (name, git(path, "rev-parse", "--short", "HEAD").strip()))
        for sha, day, subject in commits(path, days):
            by_day.setdefault(day, []).append((name, sha, subject))
    lines = ["# What changed (generated)", "",
             "%s%s from %s, the last %d days. Newest first. Each line is one commit on the default branch "
             "(a merged pull request or a direct commit): repository, short id, title. Regenerate with "
             "`python3 heim/tools/what_changed.py --repo <checkout> ...` and re-index the pack." %
             (STAMP, today, ", ".join(heads), days), ""]
    for day in sorted(by_day, reverse=True):
        block = ["## %s" % day, ""] + ["- %s `%s` %s" % c for c in by_day[day]] + [""]
        if len("\n".join(lines + block).encode("utf-8")) > MAX_BYTES:
            lines.append("(older days left out: the page is kept under the index's size limit)")
            break
        lines += block
    return "\n".join(lines).rstrip("\n") + "\n"


def main():
    ap = argparse.ArgumentParser(description="Write the knowledge pack's WHAT-CHANGED.md from git history.")
    ap.add_argument("--repo", action="append", required=True,
                    help="a checkout to read (repeat for several); NAME=PATH names it, else the folder name")
    ap.add_argument("--days", type=int, default=45, help="how far back (default 45)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="where to write (default: knowledge/WHAT-CHANGED.md)")
    a = ap.parse_args()
    repos = []
    for r in a.repo:
        name, _, path = r.partition("=") if "=" in r else (None, None, r)
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(os.path.join(path, ".git")) and not os.path.isfile(os.path.join(path, ".git")):
            sys.exit("not a git checkout: %s" % path)
        repos.append((name or os.path.basename(path.rstrip(os.sep)), path))
    text = build(repos, a.days)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s (%d KB)" % (a.out, len(text.encode("utf-8")) // 1024))


if __name__ == "__main__":
    main()
