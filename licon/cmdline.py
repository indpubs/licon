import argparse
import pathlib
import sys
from . import report
from dali.address import GearShort, GearGroup, GearBroadcast
from dali.gear.general import (
    QueryControlGearPresent,
    QueryActualLevel,
    DAPC,
    Off,
    Up,
    Down,
)
from dali.sequences import QueryDeviceTypes


class CommandTracker(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, '_commands'):
            cls._commands = []
        else:
            if hasattr(cls, "command"):
                cls._commands.append(cls)


class Command(metaclass=CommandTracker):
    @classmethod
    def add_subparsers(cls, parser):
        subparsers = parser.add_subparsers(title="commands")
        for c in cls._commands:
            description = c.description if hasattr(c, "description") \
                else c.__doc__
            help = c.help if hasattr(c, "help") else description
            parser = subparsers.add_parser(
                c.command, help=help, description=description)
            parser.set_defaults(command=c)
            c.add_arguments(parser)

    @staticmethod
    def add_arguments(parser):
        pass

    @staticmethod
    def run(args):
        pass


class ListGear(Command):
    """List all configured emergency gear"""
    command = "list"

    @staticmethod
    def run(args):
        for sitename, site in report.sites.items():
            for gear in site.gear:
                print(f"{sitename}/{gear.busname}/{gear.address}: {gear.name}")


class Scan(Command):
    """Scan for lighting gear"""
    command = "scan"

    @staticmethod
    def run(args):
        for sitename, site in report.sites.items():
            for busname, bus in site.buses.items():
                with bus as b:
                    for address in range(64):
                        cfgear = site.gearindex.get((bus, address))
                        idx = f"{sitename}/{busname}/{address}"
                        a = GearShort(address)
                        present = b.send(QueryControlGearPresent(a)).value
                        if present:
                            dts = b.send(QueryDeviceTypes(a))
                            em = 1 in dts
                        else:
                            em = False
                        has_level = b.send(QueryActualLevel(a)).value != "MASK"
                        if cfgear and not present:
                            print(f"{idx}: {cfgear.name} **MISSING**")
                        elif present and not cfgear and has_level:
                            print(f"{idx}: **NEW**")
                        elif args.verbose:
                            if cfgear:
                                print(f"{idx}: {cfgear.name}")
                            else:
                                if present and em:
                                    print(f"{idx}: **EMERGENCY UNIT**")
                                elif present and not has_level:
                                    print(f"{idx}: **NOT A LIGHT** {dts=}")


class Check(Command):
    """Check all configured emergency gear and output a status summary"""
    command = "check"

    @staticmethod
    def run(args):
        for sitename, site in report.sites.items():
            print(f"Site: {site.name}")
            if args.verbose:
                print("  - Gear:")

                def progress(gear):
                    print(f"    - {sitename}/{gear.busname}/{gear.address} — "
                          f"{gear.summary}")
                    gear.dump_state(indent=8)

            site.update(progress=progress if args.verbose else None)

            print(f"  - Overall state: {'Pass' if site.pass_ else 'Fail'}")
            print(f"  - Results: {site.results}")


class Email(Command):
    """Email status reports for all configured sites"""
    command = "email"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "--force", "-f", action="store_true",
            help="Email the report even if no failures are listed")
        parser.add_argument(
            "destination", nargs="?",
            help="Email address to receive the reports, overriding those "
            "specified in the configuration file")

    @staticmethod
    def run(args):
        for sitename, site in report.sites.items():
            if args.verbose:
                print(f"Site: {site.name}")

            def progress(gear):
                if args.verbose:
                    print(f"  - {sitename}/{gear.busname}/{gear.address} — "
                          f"{gear.summary}")

            site.update(progress=progress)
            if args.force or not site.pass_:
                if args.destination:
                    site.email_report(sitename, to=args.destination)
                else:
                    site.email_report(sitename)


class _TargetCommand(Command):
    """A command that has a target as the first positional argument"""
    @staticmethod
    def target(arg):
        xs = arg.split("/")
        if len(xs) < 1:
            raise ValueError("A site name must be specified")
        if len(xs) > 3:
            raise ValueError("Too many components in target")
        return xs

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            "--dry-run", "-n", action="store_true",
            help="Print the commands that would be sent, without sending them")
        parser.add_argument(
            "target", type=_TargetCommand.target,
            help="Target of this command: sitename[/busname[/address]]; "
            "address is a number for a single unit or 'gNUMBER' for a group")

    @staticmethod
    def get_target(args, allow_multi=True):
        ts = args.target
        # return list of (bus, address)
        site = report.sites.get(ts[0])
        if not site:
            print(f"licon: error: site {ts[0]} not known")
            return []
        if len(ts) > 1:
            bus = site.buses.get(ts[1], None)
            if not bus:
                print(f"licon: error: bus {ts[1]} not known at site {ts[0]}")
                return []
            buses = [bus]
        else:
            if allow_multi:
                buses = list(site.buses.values())
            else:
                print("licon: error: bus must be specified")
                return []
        if len(ts) > 2:
            if ts[2].startswith("g"):
                if allow_multi:
                    address = GearGroup(int(ts[2][1:]))
                else:
                    print("licon: error: group address not allowed")
                    return []
            else:
                address = GearShort(int(ts[2]))
        else:
            if allow_multi:
                address = GearBroadcast()
            else:
                print("licon: error: broadcast address not allowed")
                return []
        return [(bus, address) for bus in buses]

    @classmethod
    def send_to_target(cls, args, command):
        target = cls.get_target(args)
        if not target:
            return 1
        for bus, address in target:
            with bus as b:
                cmd = command(address)
                if args.verbose or args.dry_run:
                    print(f"{'Would send' if args.dry_run else 'Sending'} "
                          f"{cmd} on bus {bus}")
                if not args.dry_run:
                    b.send(cmd)


class LevelCmd(_TargetCommand):
    """Set the lamp to the specified level"""
    command = "level"

    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "level", type=int,
            help="Level for DAPC command, in range 0..254")

    @classmethod
    def run(cls, args):
        return cls.send_to_target(args, lambda addr: DAPC(addr, args.level))


class _SimpleCommand(_TargetCommand):
    @classmethod
    def add_arguments(cls, parser):
        assert hasattr(cls, "dali_command")
        super().add_arguments(parser)

    @classmethod
    def run(cls, args):
        return cls.send_to_target(args, lambda addr: cls.dali_command(addr))


class OffCmd(_SimpleCommand):
    """Extinguish the lamp immediately without fading"""
    command = "off"
    dali_command = Off


class UpCmd(_SimpleCommand):
    """Dim UP for 200ms"""
    command = "up"
    dali_command = Up


class DownCmd(_SimpleCommand):
    """Dim DOWN for 200ms"""
    command = "down"
    dali_command = Down


def main():
    parser = argparse.ArgumentParser(
        description="Lighting control")
    parser.add_argument(
        '--configfile', '-c', type=pathlib.Path,
        default=pathlib.Path("config.toml"),
        help="Path to configuration file")
    parser.add_argument(
        '--site', '-s', type=str, action="append",
        help="Only work on this site")
    parser.add_argument(
        '--verbose', '-v', action="store_true", default=False,
        help="Display progress while working")
    Command.add_subparsers(parser)

    args = parser.parse_args()

    try:
        with open(args.configfile, "rb") as f:
            report.read_config(f)
    except FileNotFoundError:
        print(f"Could not open config file '{args.configfile}'")
        sys.exit(1)

    if args.site:
        try:
            report.sites = {s: report.sites[s] for s in args.site}
        except KeyError as e:
            print(f"Unrecognised site '{e.args[0]}'")
            sys.exit(1)

    sys.exit(args.command.run(args))
