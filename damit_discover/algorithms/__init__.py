"""DamIT Discovery algorithms: NHD waterbodies, OSM ponds, candidate merge."""
from .discover import WaterbodiesAlgorithm, OsmPondsAlgorithm, CandidatesAlgorithm

ALGORITHMS = (WaterbodiesAlgorithm, OsmPondsAlgorithm, CandidatesAlgorithm)
