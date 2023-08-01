import tomli
from collections import Counter
import datetime
import jinja2
import smtplib
from email.message import EmailMessage
from html2text import html2text
from dali.address import GearShort
from dali.gear.general import (
    QueryControlGearPresent,
    QueryStatus,
)
from dali.gear.emergency import QueryEmergencyMode
from .daliserver import DaliServer


sites = {}


class Bus:
    def __init__(self, d, key, site):
        self.key = key
        self.site = site
        self.hostname = d["hostname"]
        self.port = d["port"]
        self.name = d.get("name", key)
        self._ds = DaliServer(host=self.hostname, port=self.port,
                              multiple_frames_per_connection=True)

    def __enter__(self):
        return self._ds.__enter__()

    def __exit__(self, *vpass):
        self._ds.__exit__(*vpass)

    def __str__(self):
        return f"{self.site.key}/{self.key}"


class Gear:
    def __init__(self, site, d):
        self.site = site
        self.busname = d["bus"]
        self.bus = site.buses[d["bus"]]
        self.address = d["address"]
        self.name = d["name"]
        self.related_emergency = d.get("related-emergency")
        self.clear()

    def clear(self):
        self._summary = None
        self.present = False
        self.related_emergency_test = False
        self.lamp_failure = False
        self.gear_failure = False

    @property
    def summary(self):
        if not self._summary:
            self._summary = self._update_summary()
        return self._summary

    def _update_summary(self):
        if not self.present:
            if self.related_emergency_test:
                return "Emergency lighting test in progress"
            return "Not present"
        if self.gear_failure:
            return "Gear failure"
        if self.lamp_failure:
            return "Lamp failure"
        return "Ok"

    @property
    def pass_(self):
        return self.summary in ("Ok", "Emergency lighting test in progress")

    def dump_state(self, indent=0):
        for line in self.list_state():
            print(f"{' ' * indent}{line}")

    def list_state(self):
        r = []

        def p(s):
            r.append(s)

        p(f"Name: {self.name}")
        if not self.present:
            p("Not present")
        if self.related_emergency_test:
            p("Emergency lighting test in progress")
        if self.lamp_failure:
            p("Lamp failure")
        if self.gear_failure:
            p("Gear failure")
        return r

    def update(self):
        self.clear()
        self.timestamp = datetime.datetime.now()
        with self.bus as b:
            b.send(self._read())

    def _check_emergency(self):
        if self.related_emergency is None:
            return
        rel_a = GearShort(self.related_emergency)
        em = yield QueryEmergencyMode(rel_a)
        if em.raw_value:
            self.related_emergency_test = \
                em.function_test or em.duration_test

    def _read(self):
        a = GearShort(self.address)

        r = yield QueryControlGearPresent(a)
        if not r.value:
            # The gear isn't responding. Check the related emergency unit.
            yield from self._check_emergency()
            return
        self.present = True

        status = yield QueryStatus(a)
        if not status.raw_value:
            self.gear_failure = True
            return
        self.gear_failure = status.ballast_status
        if status.lamp_failure:
            # Lamp failure detection can be caused by the lamp being
            # taken over by the related emergency unit.
            yield from self._check_emergency()
            if not self.related_emergency_test:
                self.lamp_failure = True


class Site:
    def __init__(self, d, key):
        self.key = key
        self.name = d["name"]
        self.email_to = d["email-to"]
        self.email_from = d["email-from"]
        self.buses = {k: Bus(v, key=k, site=self)
                      for k, v in d["buses"].items()}
        self.gear = [Gear(self, g) for g in d["gear"]]
        self.gearindex = {(g.bus, g.address): g for g in self.gear}
        self.pass_ = False
        self.results = Counter()

    def update(self, progress=None):
        self.report_time = datetime.datetime.now()
        self.pass_ = True
        self.results = Counter()
        for gear in self.gear:
            gear.update()
            self.results[gear.summary] += 1
            if not gear.pass_:
                self.pass_ = False
            if progress is not None:
                progress(gear)

    def report(self, sitename, template=None):
        env = jinja2.Environment(
            loader=jinja2.PackageLoader("licon"),
            autoescape=jinja2.select_autoescape())
        template = env.get_template(template or "report.html")
        return template.render(sitename=sitename, site=self)

    def email_report(self, sitename, to=None):
        if to is None:
            to = ', '.join(self.email_to)
        report = self.report(sitename)
        report_plain = html2text(report)
        msg = EmailMessage()
        msg['Subject'] = f"{self.name} lighting status — "\
            f"{'Pass' if self.pass_ else 'Fail'}"
        msg['From'] = self.email_from
        msg['To'] = to
        msg.preamble = "You should use a MIME-aware mail reader to view "\
            "this report.\n"
        msg.set_content(report_plain)
        msg.add_alternative(report, subtype="html")

        with smtplib.SMTP() as smtp:
            smtp.connect()
            smtp.send_message(msg)


def read_config(f):
    d = tomli.load(f)
    for k, v in d.items():
        sites[k] = Site(v, key=k)
