"""Version-independent names for QGIS 3.28 - 3.44 (Qt5) and QGIS 4.x (Qt6): new spelling
first, legacy second (the pattern of DamSafety_Hazard/compat.py)."""
from qgis.core import QgsField, QgsUnitTypes, QgsProcessing, QgsProcessingParameterFile

try:
    from qgis.core import Qgis
except ImportError:                     # pragma: no cover
    Qgis = None

try:                                    # Qt6: QtGui, Qt5: QtWidgets
    from qgis.PyQt.QtGui import QAction  # noqa: F401
except ImportError:                     # pragma: no cover
    from qgis.PyQt.QtWidgets import QAction  # noqa: F401


def first(*getters, **kw):
    for g in getters:
        try:
            v = g()
        except Exception:
            continue
        if v is not None:
            return v
    if "default" in kw:
        return kw["default"]
    raise AttributeError("no spelling of this enum exists in this QGIS build")


def _metatypes():
    try:
        from qgis.PyQt.QtCore import QMetaType
    except ImportError:
        return None
    T = getattr(QMetaType, "Type", QMetaType)
    try:
        types = {"Int": T.Int, "Double": T.Double, "String": T.QString}
        probe = QgsField("probe", types["Double"])
        if int(getattr(probe.type(), "value", probe.type())) != \
                int(getattr(types["Double"], "value", types["Double"])):
            return None
        return types
    except Exception:
        return None


_FT = _metatypes()
if _FT is None:
    from qgis.PyQt.QtCore import QVariant
    _FT = {"Int": QVariant.Int, "Double": QVariant.Double, "String": QVariant.String}
FT_INT, FT_DOUBLE, FT_STRING = _FT["Int"], _FT["Double"], _FT["String"]

FEET = first(lambda: Qgis.DistanceUnit.Feet, lambda: QgsUnitTypes.DistanceFeet)
SRC_POINT = first(lambda: Qgis.ProcessingSourceType.VectorPoint,
                  lambda: QgsProcessing.TypeVectorPoint)
SRC_LINE = first(lambda: Qgis.ProcessingSourceType.VectorLine,
                 lambda: QgsProcessing.TypeVectorLine)
SRC_POLYGON = first(lambda: Qgis.ProcessingSourceType.VectorPolygon,
                    lambda: QgsProcessing.TypeVectorPolygon)
SRC_ANY = first(lambda: Qgis.ProcessingSourceType.VectorAnyGeometry,
                lambda: QgsProcessing.TypeVectorAnyGeometry)
FILE_FILE = first(lambda: Qgis.ProcessingFileParameterBehavior.File,
                  lambda: QgsProcessingParameterFile.File)


def feet_to_map_units(crs):
    """Map units per foot of a projected CRS (None for a geographic CRS)."""
    if crs.isGeographic():
        return None
    return QgsUnitTypes.fromUnitToUnitFactor(FEET, crs.mapUnits())


def _vfw():
    from qgis.core import QgsVectorFileWriter as W
    return W


OVERWRITE_FILE = first(lambda: _vfw().ActionOnExistingFile.CreateOrOverwriteFile,
                       lambda: _vfw().CreateOrOverwriteFile)
OVERWRITE_LAYER = first(lambda: _vfw().ActionOnExistingFile.CreateOrOverwriteLayer,
                        lambda: _vfw().CreateOrOverwriteLayer)
WRITER_NO_ERROR = first(lambda: _vfw().WriterError.NoError, lambda: _vfw().NoError)
