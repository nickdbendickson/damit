"""Qt5 / Qt6 and QGIS 3.28 - 4.x enum compatibility (scoped enums moved to Qgis in 3.36)."""
from qgis.core import Qgis, QgsProcessing, QgsProcessingParameterFile


def _pick(new_owner, new_name, old_owner, old_name):
    obj = getattr(Qgis, new_owner, None)
    if obj is not None and hasattr(obj, new_name):
        return getattr(obj, new_name)
    return getattr(old_owner, old_name)


FILE_FOLDER = _pick("ProcessingFileParameterBehavior", "Folder", QgsProcessingParameterFile, "Folder")
FILE_FILE = _pick("ProcessingFileParameterBehavior", "File", QgsProcessingParameterFile, "File")
VECTOR_POINT = _pick("ProcessingSourceType", "VectorPoint", QgsProcessing, "TypeVectorPoint")
VECTOR_ANY = _pick("ProcessingSourceType", "VectorAnyGeometry", QgsProcessing, "TypeVectorAnyGeometry")
