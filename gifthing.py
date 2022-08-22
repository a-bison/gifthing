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


def add_file_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file", help="The file to operate on.")


def open_and_verify_gif(parser: argparse.ArgumentParser, fpath: str) -> gifmeta.Gif:
    try:
        return gifmeta.Gif(fpath)
    except GifStreamException as e:
        parser.error(f"{fpath}: not a valid GIF file")


def open_and_verify_gifstream(parser: argparse.ArgumentParser, fpath: str) -> GifStream:
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
    def __init__(
        self,
        constant_elems: t.Container[int] = (),
        always_use_first_offset: bool = False
    ) -> None:
        self.first_offset = (0.0, 0.0, 0.0)
        self.first_offset_set = False
        self.always_use_first_offset = always_use_first_offset
        self.constant_elems = constant_elems

    # Generate a new offset.
    def generate_offset(self) -> t.Tuple[float, float, float]:
        offset = [random.random() if not n in self.constant_elems else 0.0 for n in range(3)]
        offset_t = tuple(offset)

        if not self.first_offset_set:
            self.first_offset = offset_t
            self.first_offset_set = True

        return offset_t # type: ignore

    # Get a new offset, taking into account first offset settings
    def get_next_offset(self) -> t.Tuple[float, float, float]:
        if self.always_use_first_offset and self.first_offset_set:
            return self.first_offset

        return self.generate_offset()

    # Generate a color, taking into account constant_offset
    def generate_color(self, original_color: t.Tuple[float, float, float]) -> t.Tuple[float, float, float]:
        offset = self.get_next_offset()

        new_color = tuple([
            (original + offset) % 1.0 for original, offset in zip(original_color, offset)
        ])

        return new_color  # type: ignore

    def generate_table(
        self,
        original_table: t.Iterable[t.Tuple[float, float, float]]
    ) -> t.Sequence[t.Tuple[float, float, float]]:
        return [self.generate_color(color) for color in original_table]


def gen_rand_rgb_colortable(original_table: t.Iterable[t.Tuple[float, float, float]], generator: ColorGenerator) -> bytes:
    rgb_table = generator.generate_table(original_table)
    return table_float_to_bytes(rgb_table)


# Generate the coordinates in HSV, but output RGB.
def gen_rand_hsv_colortable(original_table: t.Iterable[t.Tuple[float, float, float]], generator: ColorGenerator) -> bytes:
    # colorsys uses all 0 to 1 for HSV, which is more convenient for us
    hsv_table = generator.generate_table(table_rgb_to_hsv(original_table))
    return table_float_to_bytes(table_hsv_to_rgb(hsv_table))


def table_hsv_to_rgb(hsv_table: t.Iterable[t.Tuple[float, float, float]]) -> t.Sequence[t.Tuple[float, float, float]]:
    # Convert to RGB
    rgb_table = [colorsys.hsv_to_rgb(*color) for color in hsv_table]
    return rgb_table


def table_rgb_to_hsv(rgb_table: t.Iterable[t.Tuple[float, float, float]]) -> t.Sequence[t.Tuple[float, float, float]]:
    hsv_table = [colorsys.rgb_to_hsv(*color) for color in rgb_table]
    return hsv_table


def table_int_to_float(table: t.Iterable[t.Tuple[int, int, int]]) -> t.Sequence[t.Tuple[float, float, float]]:
    return [(float(x / 255), float(y / 255), float(z / 255)) for x, y, z in table]


def table_float_to_bytes(table: t.Iterable[t.Tuple[float, float, float]]) -> bytes:
    return bytes((int(255 * x) for x in itertools.chain.from_iterable(table)))


def mode_randcolor(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    gif = open_and_verify_gif(parser, args.file)

    gifstream = open_and_verify_gifstream(parser, args.file)
    screen_desc = gifstream.consume_screen_descriptor()

    if not screen_desc.colortable_exists:
        parser.error(f"{args.file}: global color table is not present")

    float_table = table_int_to_float(gif.colortable)
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


CHAR_TO_COLOR_ELEM = {
    "r": 0,
    "g": 1,
    "b": 2,
    "h": 0,
    "s": 1,
    "v": 2
}


def calc_hold_set(parser: argparse.ArgumentParser, hold_str: str) -> t.Set[int]:
    charset = set(hold_str.lower())

    for c in charset:
        if c not in CHAR_TO_COLOR_ELEM:
            parser.error(f"--hold: bad char {c}, only these chars may be used: {''.join(CHAR_TO_COLOR_ELEM.keys())}")

    return {CHAR_TO_COLOR_ELEM[c] for c in charset}


def prepare_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

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
        "--rgb", action="store_true", help="Generate using RGB color space."
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

    random.seed()

    args.func(parser, args)


if __name__ == "__main__":
    main()
