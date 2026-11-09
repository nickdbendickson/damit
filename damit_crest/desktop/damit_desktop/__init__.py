"""DamIT Crest desktop: a native window around the built web desk (damit_desktop/web/).

There is no Python copy of the breach engine. The desk is the TypeScript app in damit_crest/src, bundled by
`npm run build:desktop` into damit_desktop/web/. This package serves those files, saves exports, and, from the
Report step, writes the dam folder and calls the DamIT QGIS plugins installed on this computer through qgis_process
(algorithm ids in algorithms.py; docs/HANDOFF.md).
"""

WEB_DIR_NAME = "web"
