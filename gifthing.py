import argparse
import colorsys
import pathlib
import itertools
import sys
import random
import typing as t

import gifmeta
from gifmeta.gif import _GifStream as GifStream
from gifmeta.gif import GifStreamException


__version__ = "0.1.0"


def add_file_arg(parser: argparse.ArgumentParser) -> None:
    """
    Add a file argument to an argument parser.
    """
    parser.add_argument("file", help="The file to operate on.")


def open_and_verify_gif(parser: argparse.ArgumentParser, fpath: str) -> gifmeta.Gif:
    """
    Open a GIF, verify it, and read all metadata.
    """
    try:
        return gifmeta.Gif(fpath)
    except GifStreamException as e:
        parser.error(f"{fpath}: not a valid GIF file")


def open_and_verify_gifstream(parser: argparse.ArgumentParser, fpath: str) -> GifStream:
    """
    Open a GIF, verify it, and place the stream head at the screen descriptor.
    """
    path = pathlib.Path(fpath)

    if not path.exists():
        parser.error(f"{path}: does not exist.")

    if not path.is_file():
        parser.error(f"{path}: must be a file.")

    gifstream = GifStream(str(path))

    try:
        gifstream.consume_header()
    except GifStreamException as e:
        parser.error(f"{path}: not a valid GIF file")

    return gifstream


class ColorGenerator:
    """
    The generator for colors. Takes an input color, and randomly transforms it according to
    instance configuration. At its core, works by generating random offsets and adding them
    to the input colors.
    """
    def __init__(
        self,
        constant_elems: t.Container[int] = (),
        always_use_first_offset: bool = False
    ) -> None:
        """
        Args:
            constant_elems: Element indices to keep constant during color generation.
            always_use_first_offset: Instead of generating a new offset every time, generate one
                offset and use it for every color modified.
        """
        self.first_offset = (0.0, 0.0, 0.0)
        self.first_offset_set = False
        self.always_use_first_offset = always_use_first_offset
        self.constant_elems = constant_elems

    def generate_offset(self) -> t.Tuple[float, float, float]:
        """
        Generate a new color offset. All elements will be 0.0 - 1.0.
        """
        offset = [random.random() if not n in self.constant_elems else 0.0 for n in range(3)]
        offset_t = tuple(offset)

        if not self.first_offset_set:
            self.first_offset = offset_t
            self.first_offset_set = True

        return offset_t  # type: ignore

    def get_next_offset(self) -> t.Tuple[float, float, float]:
        """
        Get the next offset according to all generator configuration. Not to be confused with generate_offset(),
        which always creates a new offset.
        """
        if self.always_use_first_offset and self.first_offset_set:
            return self.first_offset

        return self.generate_offset()

    def generate_color(self, original_color: t.Tuple[float, float, float]) -> t.Tuple[float, float, float]:
        """
        Generate a new color based on an input color.
        """
        offset = self.get_next_offset()

        # Generate color by adding a generated offset to the original color. If this sum exceeds 1.0, it will
        # wrap back around, starting from 0.0
        new_color = tuple([
            (original + offset) % 1.0 for original, offset in zip(original_color, offset)
        ])

        return new_color  # type: ignore

    def generate_table(
        self,
        original_table: t.Iterable[t.Tuple[float, float, float]]
    ) -> t.Sequence[t.Tuple[float, float, float]]:
        """
        Convenience function. Generates a full color table using another as input.
        """
        return [self.generate_color(color) for color in original_table]


def gen_rand_rgb_colortable(original_table: t.Iterable[t.Tuple[float, float, float]], generator: ColorGenerator) -> bytes:
    """
    Randomize a GIF's color table using the provided color generator.
    """
    rgb_table = generator.generate_table(original_table)
    return table_float_to_bytes(rgb_table)


def gen_rand_hsv_colortable(original_table: t.Iterable[t.Tuple[float, float, float]], generator: ColorGenerator) -> bytes:
    """
    Convert the color table to HSV, randomize it in that space, then convert back to RGB.

    There are some flaws in the HSV color space (outlined here https://en.wikipedia.org/wiki/HSL_and_HSV#Disadvantages),
    but it's good enough to mess around with some GIFs. It can produce some interesting effects.
    """
    hsv_table = generator.generate_table(table_rgb_to_hsv(original_table))
    return table_float_to_bytes(table_hsv_to_rgb(hsv_table))


def table_hsv_to_rgb(hsv_table: t.Iterable[t.Tuple[float, float, float]]) -> t.Sequence[t.Tuple[float, float, float]]:
    """
    Convert a float format table from HSV to RGB space.
    """
    rgb_table = [colorsys.hsv_to_rgb(*color) for color in hsv_table]
    return rgb_table


def table_rgb_to_hsv(rgb_table: t.Iterable[t.Tuple[float, float, float]]) -> t.Sequence[t.Tuple[float, float, float]]:
    """
    Convert a float format table from RGB to HSV space.
    """
    hsv_table = [colorsys.rgb_to_hsv(*color) for color in rgb_table]
    return hsv_table


def table_int_to_float(table: t.Iterable[t.Tuple[int, int, int]]) -> t.Sequence[t.Tuple[float, float, float]]:
    """
    Convert from a gifmeta format colortable (0-255 ints) to a common format (0.0-1.0 floats).
    """
    return [(float(x / 255), float(y / 255), float(z / 255)) for x, y, z in table]


def table_float_to_bytes(table: t.Iterable[t.Tuple[float, float, float]]) -> bytes:
    """
    Convert from the common float table format to bytes for writing back into a GIF.
    """
    return bytes((int(255 * x) for x in itertools.chain.from_iterable(table)))


def mode_randcolor(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """
    Randomize the color table of a GIF according to various parameters.
    """

    # Parse the GIF, and open a stream into it.
    gif = open_and_verify_gif(parser, args.file)
    gifstream = open_and_verify_gifstream(parser, args.file)

    # Consume screen descriptor and position the gif stream at the global color table.
    screen_desc = gifstream.consume_screen_descriptor()

    if not screen_desc.colortable_exists:
        parser.error(f"{args.file}: global color table is not present")

    # Convert to float 0.0 - 1.0 format.
    float_table = table_int_to_float(gif.colortable)

    # Configure color generator.
    hold_set = calc_hold_set(parser, args.hold)
    generator = ColorGenerator(
        constant_elems=hold_set,
        always_use_first_offset=args.constant_offset
    )

    # Generate a random color table and write it to the stream.
    if args.hsv:
        rand_colortable = gen_rand_hsv_colortable(float_table, generator)
    else:
        if not args.rgb:
            print(f"{parser.prog}: warn: color mode not specified, defaulting to --rgb", file=sys.stderr)

        rand_colortable = gen_rand_rgb_colortable(float_table, generator)

    gifstream.stream.write(rand_colortable)

    # done.
    gifstream.close()


# Map of characters in --hold string to color element indices.
CHAR_TO_COLOR_ELEM = {
    "r": 0,
    "g": 1,
    "b": 2,
    "h": 0,
    "s": 1,
    "v": 2
}


def calc_hold_set(parser: argparse.ArgumentParser, hold_str: str) -> t.Set[int]:
    """
    Implements the conversion between a --hold string and the Set used to control a ColorGenerator instance.
    """
    charset = set(hold_str.lower())

    for c in charset:
        if c not in CHAR_TO_COLOR_ELEM:
            parser.error(f"--hold: bad char {c}, only these chars may be used: {''.join(CHAR_TO_COLOR_ELEM.keys())}")

    return {CHAR_TO_COLOR_ELEM[c] for c in charset}


def prepare_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument("--version", "-v", action="store_true", help="Print the current version number.")

    mode_parsers = parser.add_subparsers(
        title="mode",
        description="The mode to operate in."
    )

    mode_randcolor_parser = mode_parsers.add_parser(
        "randcolor",
        help="Randomize a GIF's color table."
    )
    mode_randcolor_parser.set_defaults(func=mode_randcolor)
    add_file_arg(mode_randcolor_parser)

    color_mode_group = mode_randcolor_parser.add_mutually_exclusive_group()
    color_mode_group.add_argument(
        "--rgb", action="store_true", help="Generate using RGB color space. This is the default."
    )
    color_mode_group.add_argument(
        "--hsv", action="store_true", help="Generate using HSV color space"
    )

    mode_randcolor_parser.add_argument(
        "--hold", default="", help=(
            "Hold certain elements of a color constant. For example, if --hold rb is specified, only green (g) "
            "would be randomized. A similar idea holds for HSV."
        )
    )
    mode_randcolor_parser.add_argument(
        "--constant-offset", dest="constant_offset", action="store_true", help=(
            "Only randomly generate a color value offset, and then apply it to each color, rather than "
            "fully randomizing everything."
        )
    )

    return parser


def main() -> None:
    parser = prepare_argparser()
    args = parser.parse_args()

    if args.version:
        print(__version__)
        sys.exit(0)

    if not hasattr(args, "func"):
        parser.error("Mode must be specified.")

    random.seed()
    args.func(parser, args)


if __name__ == "__main__":
    main()
