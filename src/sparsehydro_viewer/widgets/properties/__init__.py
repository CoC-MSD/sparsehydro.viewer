"""Property editor modelled on QPropertyModel (tree of typed properties with matching editors)."""

from .adapters import from_option_specs, node_properties
from .delegate import PropertyDelegate
from .editor import PropertyEditor
from .model import MIXED_TEXT, PropertyModel
from .node import MIXED, Hints, PropertyNode

__all__ = ["MIXED", "MIXED_TEXT", "Hints", "PropertyDelegate", "PropertyEditor", "PropertyModel", "PropertyNode",
           "from_option_specs", "node_properties"]
