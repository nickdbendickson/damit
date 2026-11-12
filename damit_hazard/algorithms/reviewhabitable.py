"""damit:reviewhabitable - the engineer's habitability review of structures (DamIT Hazard 0.4.0).

Only an ND 911 address point is habitable by itself. Every other structure (NSI, USA Structures, ...) is "unverified"
until an engineer reviews it here: this tool saves reviewed_habitable = habitable / not habitable (or removes the review)
for the structure keys it is given, in habitable_review.json in the dam folder. damit:classify, the depth-velocity chart
and the Screener only READ that file; this tool is the only thing that writes it, and only when run. The keys are the
struct_key column of the chart's worklist (damit_hazard_dv_habitable_unverified.csv) or of the receptors GeoPackage.
"""
import os

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingOutputFile,
                       QgsProcessingParameterEnum, QgsProcessingParameterFile, QgsProcessingParameterString)

from .. import compat
from ..engine import habitable_review
from ..engine.habitable_review import keys_from

DECISIONS = ["Habitable (an engineer reviewed: people live or work there)", "Not habitable (reviewed)",
             "Remove the review (back to unverified)"]
VALUES = [True, False, None]


class ReviewHabitable(QgsProcessingAlgorithm):
    def name(self):
        return "reviewhabitable"

    def displayName(self):
        return "Review habitable structures (engineer sign-off)"

    def group(self):
        return ""

    def groupId(self):
        return ""

    def shortHelpString(self):
        return ("Saves an engineer's habitability decision for structures that are not ND 911 address points. Only ND 911 "
                "address points are habitable by themselves; every other structure stays 'unverified' (counted, not "
                "plotted on the depth-velocity chart) until it is reviewed here. The decision goes into "
                "habitable_review.json in the dam folder; damit:classify, the chart and the Screener only read it. "
                "Give the structure keys (the struct_key column of damit_hazard_dv_habitable_unverified.csv, typed "
                "or as the CSV), the decision and who decided. 'Remove' deletes the review. Every change is kept in "
                "the file's history. NSI occtype and USA Structures only SUGGEST: they never decide.")

    def createInstance(self):
        return ReviewHabitable()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(
            "FOLDER", "Dam folder (habitable_review.json is created or updated in it) or the path of the review file"))
        self.addParameter(QgsProcessingParameterString(
            "KEYS", "Structure keys (comma, semicolon or one per line; the struct_key column of the worklist)",
            multiLine=True, optional=True))
        self.addParameter(QgsProcessingParameterFile(
            "KEYS_CSV", "Or a CSV with a struct_key column (e.g. the unverified worklist, edited to the rows reviewed)",
            behavior=compat.FILE_FILE, extension="csv", optional=True))
        self.addParameter(QgsProcessingParameterEnum("DECISION", "Decision", options=DECISIONS, defaultValue=0))
        self.addParameter(QgsProcessingParameterString("REVIEWER", "Reviewed by (name of the engineer)"))
        self.addParameter(QgsProcessingParameterString("NOTE", "Note (why; e.g. site visit, aerial photo)", optional=True))
        self.addOutput(QgsProcessingOutputFile("REVIEW_FILE", "habitable_review.json"))

    def processAlgorithm(self, p, context, feedback):
        folder = self.parameterAsString(p, "FOLDER", context).strip()
        if not folder:
            raise QgsProcessingException("Give the dam folder or the review file path.")
        path = folder if folder.lower().endswith(".json") else os.path.join(folder, habitable_review.REVIEW_FILE)
        try:
            keys = keys_from(self.parameterAsString(p, "KEYS", context), self.parameterAsFile(p, "KEYS_CSV", context))
            dec = VALUES[self.parameterAsEnum(p, "DECISION", context)]
            habitable_review.sign_off(path, keys, dec, self.parameterAsString(p, "REVIEWER", context),
                                      self.parameterAsString(p, "NOTE", context))
        except (ValueError, OSError) as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo("{} structure(s): {} in {}".format(
            len(keys), {True: "reviewed habitable", False: "reviewed not habitable", None: "review removed"}[dec], path))
        return {"REVIEW_FILE": path}
