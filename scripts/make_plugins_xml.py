#!/usr/bin/env python3
"""Write plugins.xml, the QGIS plugin repository index, for the DamIT zips of one release.

    python3 scripts/make_plugins_xml.py --tag v0.8.0 --zips dist --out pages/plugins.xml
    python3 scripts/make_plugins_xml.py --tag v0.8.0 --zips dist --out pages/plugins.xml \\
        --merge old-plugins.xml      (keep entries already published for plugins not in this release)

One <pyqgis_plugin> per zip in --zips (<plugin>_<major>_<minor>_<patch>.zip, as
scripts/package_plugins.py names them), filled from the plugin's metadata.txt inside the zip,
with download_url pointing at the GitHub Release asset:
  https://github.com/nickdbendickson/damit/releases/download/<tag>/<zip>
QGIS reads the index from the URL the user adds under Plugins > Manage and Install Plugins >
Settings > Add (https://nickdbendickson.github.io/damit/plugins.xml, published to the gh-pages
branch by .github/workflows/release.yml).

Adapted from DWR_Plugins tools/make_plugins_xml.py (same fields, same merge rule). Pure stdlib."""
import argparse
import configparser
import datetime
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

RELEASE_URL = "https://github.com/nickdbendickson/damit/releases/download/{tag}/{zip}"
PAGES_URL = "https://nickdbendickson.github.io/damit/plugins.xml"
ZIP_RE = re.compile(r"^(damit_[a-z0-9]+)_(\d+)_(\d+)_(\d+)\.zip$")
# metadata key -> plugins.xml element (in the order the official repository writes them)
FIELDS = (("description", "description"), ("about", "about"), ("version", "version"),
          ("qgisMinimumVersion", "qgis_minimum_version"), ("qgisMaximumVersion", "qgis_maximum_version"),
          ("homepage", "homepage"), ("author", "author_name"), ("tracker", "tracker"),
          ("repository", "repository"), ("tags", "tags"), ("experimental", "experimental"),
          ("deprecated", "deprecated"), ("supportsQt6", "supports_qt6"))


def zip_version(zip_name):
    m = ZIP_RE.match(zip_name)
    return "{}.{}.{}".format(*m.group(2, 3, 4)) if m else None


def read_metadata(zip_path):
    """(plugin folder, {key: value}) from the metadata.txt inside a plugin zip."""
    with zipfile.ZipFile(zip_path) as z:
        metas = [n for n in z.namelist() if n.count("/") == 1 and n.endswith("/metadata.txt")]
        if len(metas) != 1:
            raise SystemExit("{}: expected one <plugin>/metadata.txt, found {}".format(zip_path, metas))
        folder = metas[0].split("/")[0]
        # QGIS reads metadata.txt with configparser (% interpolation), so read it the same way
        cp = configparser.ConfigParser()
        cp.read_string(z.read(metas[0]).decode("utf-8-sig"))
        return folder, {k: cp.get("general", k) for k in cp.options("general")}


def plugin_element(zip_name, meta, folder, tag, date):
    name = meta.get("name") or folder
    el = ET.Element("pyqgis_plugin", name=name, version=meta.get("version", "").strip())
    lower = {k.lower(): v for k, v in meta.items()}
    for key, tagname in FIELDS:
        val = lower.get(key.lower(), "")
        if key in ("experimental", "deprecated", "supportsQt6"):
            val = "True" if str(val).strip().lower() in ("true", "1", "yes") else "False"
        ET.SubElement(el, tagname).text = val.strip()
    ET.SubElement(el, "file_name").text = zip_name
    ET.SubElement(el, "icon").text = "{}/{}".format(folder, lower.get("icon", "icon.svg").strip())
    ET.SubElement(el, "download_url").text = RELEASE_URL.format(tag=tag, zip=zip_name)
    ET.SubElement(el, "update_date").text = date
    ET.SubElement(el, "create_date").text = date
    return el


def merge_existing(path, new_names):
    """The <pyqgis_plugin> elements of an existing plugins.xml for plugins not in this release."""
    if not path or not os.path.isfile(path):
        return []
    try:
        old = ET.parse(path).getroot()
    except ET.ParseError as e:
        print("NOTE: {} not merged (not well-formed: {})".format(path, e), file=sys.stderr)
        return []
    return [el for el in old.findall("pyqgis_plugin") if el.get("name") not in new_names]


def build(tag, zips_dir, merge="", date=""):
    """The <plugins> root element for the zips in zips_dir."""
    date = date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    root = ET.Element("plugins")
    names = set()
    zips = sorted(n for n in os.listdir(zips_dir) if ZIP_RE.match(n))
    if not zips:
        raise SystemExit("no damit_<plugin>_<x_y_z>.zip in " + zips_dir)
    for zip_name in zips:
        folder, meta = read_metadata(os.path.join(zips_dir, zip_name))
        if zip_version(zip_name) != meta.get("version", "").strip():
            raise SystemExit("{}: zip name version != metadata.txt version {}".format(
                zip_name, meta.get("version")))
        if folder != ZIP_RE.match(zip_name).group(1):
            raise SystemExit("{}: holds folder {}".format(zip_name, folder))
        el = plugin_element(zip_name, meta, folder, tag, date)
        names.add(el.get("name"))
        root.append(el)
        print("{} {} -> {}".format(el.get("name"), el.get("version"), el.find("download_url").text))
    for el in merge_existing(merge, names):
        root.append(el)
        print("kept {} {} from {}".format(el.get("name"), el.get("version"), merge))
    try:
        ET.indent(root)                                  # Python 3.9+
    except AttributeError:
        pass
    return root


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--tag", required=True, help="the release tag the zips are uploaded under")
    ap.add_argument("--zips", required=True, help="folder with the damit_<plugin>_<x_y_z>.zip files")
    ap.add_argument("--out", required=True, help="plugins.xml to write")
    ap.add_argument("--merge", default="", help="an existing plugins.xml whose other plugins are kept")
    ap.add_argument("--date", default="", help="update_date (YYYY-MM-DD) [today, UTC]")
    a = ap.parse_args(argv)
    root = build(a.tag, a.zips, a.merge, a.date)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    ET.ElementTree(root).write(a.out, encoding="utf-8", xml_declaration=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
