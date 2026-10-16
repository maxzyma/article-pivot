from __future__ import annotations

import unittest

from article_pivot.model import Block
from article_pivot.renderers import _render_block


def table(headers, rows) -> Block:
    return Block(id="t", type="table", attrs={"headers": headers, "rows": rows})


class TableRenderingTests(unittest.TestCase):
    def test_spanning_header_widens_to_the_widest_row(self):
        # A single title cell spanning two columns: Markdown would drop every
        # row cell beyond the header width, so the header must be padded.
        text = _render_block(table(["Best practices"], [["Question?", "Answer."]]), 2)
        self.assertEqual(
            "| Best practices |  |\n| --- | --- |\n| Question? | Answer. |",
            text,
        )

    def test_short_rows_are_padded_to_the_header_width(self):
        text = _render_block(table(["A", "B"], [["only"]]), 2)
        self.assertEqual("| A | B |\n| --- | --- |\n| only |  |", text)


if __name__ == "__main__":
    unittest.main()
