"""Receptor-layer symbology by suggested class. Hazard-class colours belong to the product
(DamSafety docs/gui-grammar.md: map styles keep their own palette); the low / significant /
high fills reuse the REG_05.2026 Fig. 5.1 zone colours the DamSafety suite uses."""
CLASS_COLOURS = {
    -1: ("#BDBDBD", "No hit"),
    0: ("#E0E0E0", "Minimal"),
    1: ("#C4E0AD", "Low"),
    2: ("#F9F4A3", "Significant"),
    3: ("#EF9897", "High"),
    4: ("#8E1B1B", "Extremely High"),
}


def apply(layer, labels):
    """Categorised renderer on the 'class' field, legend in the run's local labels."""
    from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol
    from qgis.PyQt.QtGui import QColor
    cats = []
    for k, (col, generic) in sorted(CLASS_COLOURS.items()):
        sym = QgsSymbol.defaultSymbol(layer.geometryType())
        sym.setColor(QColor(col))
        name = labels.get(k, generic) if k >= 0 else generic
        cats.append(QgsRendererCategory(k, sym, name))
    layer.setRenderer(QgsCategorizedSymbolRenderer("class", cats))
    layer.triggerRepaint()
