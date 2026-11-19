from ._ffi import ffi as ffi, lib as lib
from .core import Terminal as Terminal, UnknownSequence as UnknownSequence

__version__: str

class GhosttyError(RuntimeError): ...
