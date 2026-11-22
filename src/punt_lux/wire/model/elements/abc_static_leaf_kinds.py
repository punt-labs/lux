"""Static leaf-kind wiring, separate from handler-bearing leaves."""

from __future__ import annotations

from punt_lux.wire.model.elements.abc_kind_codec import KindCodec
from punt_lux.wire.model.elements.abc_kind_spec import AbcKindSpec
from punt_lux.wire.model.elements.abc_leaf_spec import LeafKindSpec
from punt_lux.wire.model.elements.draw import DrawElement
from punt_lux.wire.model.elements.draw_codec import JsonDrawDecoder, JsonDrawEncoder
from punt_lux.wire.model.elements.image import ImageElement
from punt_lux.wire.model.elements.image_codec import JsonImageDecoder, JsonImageEncoder
from punt_lux.wire.model.elements.markdown import MarkdownElement
from punt_lux.wire.model.elements.markdown_codec import (
    JsonMarkdownDecoder,
    JsonMarkdownEncoder,
)
from punt_lux.wire.model.elements.plot import PlotElement
from punt_lux.wire.model.elements.plot_codec import JsonPlotDecoder, JsonPlotEncoder
from punt_lux.wire.model.elements.progress import ProgressElement
from punt_lux.wire.model.elements.progress_codec import (
    JsonProgressDecoder,
    JsonProgressEncoder,
)
from punt_lux.wire.model.elements.separator import SeparatorElement
from punt_lux.wire.model.elements.separator_codec import (
    JsonSeparatorDecoder,
    JsonSeparatorEncoder,
)
from punt_lux.wire.model.elements.spinner import SpinnerElement
from punt_lux.wire.model.elements.spinner_codec import (
    JsonSpinnerDecoder,
    JsonSpinnerEncoder,
)
from punt_lux.wire.model.elements.terminal import (
    JsonTerminalDecoder,
    JsonTerminalEncoder,
    TerminalElement,
)
from punt_lux.wire.model.elements.text import TextElement
from punt_lux.wire.model.elements.text_codec import JsonTextDecoder, JsonTextEncoder
from punt_lux.wire.model.elements.tree import TreeElement
from punt_lux.wire.model.elements.tree_codec import JsonTreeDecoder, JsonTreeEncoder


class StaticLeafKinds:
    """Specs for elements that carry content but no interaction handlers."""

    @staticmethod
    def specs() -> list[AbcKindSpec]:
        return [
            LeafKindSpec(
                kind="text",
                codec=KindCodec(TextElement, JsonTextDecoder, JsonTextEncoder().encode),
            ),
            LeafKindSpec(
                kind="progress",
                codec=KindCodec(
                    ProgressElement, JsonProgressDecoder, JsonProgressEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="markdown",
                codec=KindCodec(
                    MarkdownElement, JsonMarkdownDecoder, JsonMarkdownEncoder().encode
                ),
            ),
            LeafKindSpec(  # SPIKE: terminal element (spike/terminal-ghostty)
                kind="terminal",
                codec=KindCodec(
                    TerminalElement, JsonTerminalDecoder, JsonTerminalEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="spinner",
                codec=KindCodec(
                    SpinnerElement, JsonSpinnerDecoder, JsonSpinnerEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="separator",
                codec=KindCodec(
                    SeparatorElement,
                    JsonSeparatorDecoder,
                    JsonSeparatorEncoder().encode,
                ),
            ),
            LeafKindSpec(
                kind="image",
                codec=KindCodec(
                    ImageElement, JsonImageDecoder, JsonImageEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="tree",
                codec=KindCodec(TreeElement, JsonTreeDecoder, JsonTreeEncoder().encode),
            ),
            LeafKindSpec(
                kind="plot",
                codec=KindCodec(PlotElement, JsonPlotDecoder, JsonPlotEncoder().encode),
            ),
            LeafKindSpec(
                kind="draw",
                codec=KindCodec(DrawElement, JsonDrawDecoder, JsonDrawEncoder().encode),
            ),
        ]
