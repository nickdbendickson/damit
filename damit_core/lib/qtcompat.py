"""Qt5 / Qt6 (QGIS 3.x / 4.x) names used by the DamIT plugins."""
try:
    from qgis.PyQt.QtGui import QAction          # Qt6
except ImportError:                              # pragma: no cover - Qt5
    from qgis.PyQt.QtWidgets import QAction      # noqa: F401


def exec_dialog(dlg):
    run = getattr(dlg, "exec", None) or getattr(dlg, "exec_")
    return run()


def field_types():
    """{'Int', 'Double', 'String'} -> the type QgsField accepts in this QGIS build (QMetaType on
    QGIS >= 3.38 / 4, the legacy variant type on older builds)."""
    from qgis.core import QgsField
    try:
        from qgis.PyQt.QtCore import QMetaType
        T = getattr(QMetaType, "Type", QMetaType)
        t = {"Int": T.Int, "Double": T.Double, "String": T.QString}
        probe = QgsField("probe", t["Double"])
        if int(getattr(probe.type(), "value", probe.type())) == int(getattr(t["Double"], "value", t["Double"])):
            return t
    except Exception:                            # noqa: BLE001
        pass
    from qgis.PyQt.QtCore import QVariant        # QGIS < 3.38 only (Qt5)
    return {"Int": QVariant.Int, "Double": QVariant.Double, "String": QVariant.String}


def make_fields(spec):
    """QgsFields from [(name, 'Int'|'Double'|'String')]."""
    from qgis.core import QgsField, QgsFields
    t = field_types()
    fs = QgsFields()
    for name, kind in spec:
        fs.append(QgsField(name, t[kind]))
    return fs
