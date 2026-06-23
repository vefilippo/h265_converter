from transcoder.cli import build_parser


def test_parser_defaults():
    args = build_parser().parse_args(["run", "all"])
    assert args.command == "run"
    assert args.app == "all"
    assert args.scope == "all"


def test_parser_scan_with_filters():
    args = build_parser().parse_args(["scan", "sonarr", "new", "--show", "Breaking Bad"])
    assert args.command == "scan"
    assert args.app == "sonarr"
    assert args.scope == "new"
    assert args.show == "Breaking Bad"


def test_parser_queue_no_app_required():
    args = build_parser().parse_args(["queue"])
    assert args.command == "queue"
    assert args.app == "all"
    assert args.scope == "all"
