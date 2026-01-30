"""
timeparse.py
(c) Will Roberts <wildwilhelm@gmail.com>  1 February, 2014
(c) Sóla Lusøt (solaluset) 2026

Implements a single function, `timeparse`, which can parse various
kinds of time expressions.
"""

# MIT LICENSE
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import re
from datetime import datetime, timedelta
from typing import Literal

# fmt: off

SIGN        = r"(?P<sign>[+|-])?"
NUMBER      = r"(\d+(?:\.\d*)?|\.\d+)"
YEARS       = r"(?P<years>\d+)\s*(?:ys?|yrs?|years?)"
MONTHS      = r"(?P<months>\d+)\s*(?:mos?|mths?|months?)"
WEEKS       = fr"(?P<weeks>{NUMBER})\s*(?:w|wks?|weeks?)"
DAYS        = fr"(?P<days>{NUMBER})\s*(?:d|dys?|days?)"
HOURS       = fr"(?P<hours>{NUMBER})\s*(?:h|hrs?|hours?)"
MINS        = fr"(?P<mins>{NUMBER})\s*(?:m|mins?|minutes?)"
SECS        = fr"(?P<secs>{NUMBER})\s*(?:s|secs?|seconds?)"
SEPARATORS  = r"[,/]"
SECCLOCK    = fr":?(?P<secs>{NUMBER})"
MINCLOCK    = r"(?P<mins>\d+):(?P<secs>\d{2}(?:\.\d+)?)"
HOURCLOCK   = r"(?P<hours>\d+):(?P<mins>\d{2}):(?P<secs>\d{2}(?:\.\d+)?)"
DAYCLOCK    = r"(?P<days>\d+):(?P<hours>\d{2}):" \
              r"(?P<mins>\d{2}):(?P<secs>\d{2}(?:\.\d+)?)"

OPT         = lambda x: r"(?:{x})?".format(x=x)
OPTSEP      = lambda x: r"(?:{x}\s*(?:{SEPARATORS}\s*)?)?".format(
                  x=x, SEPARATORS=SEPARATORS
              )

# fmt: on

TIMEFORMATS = [
    r"P?{YEARS}{MONTHS}{WEEKS}{DAYS}T?{HOURS}{MINS}{SECS}".format(
        YEARS=OPTSEP(YEARS),
        MONTHS=OPTSEP(MONTHS),
        WEEKS=OPTSEP(WEEKS),
        DAYS=OPTSEP(DAYS),
        HOURS=OPTSEP(HOURS),
        MINS=OPTSEP(MINS),
        SECS=OPT(SECS),
    ),
    r"{MINCLOCK}".format(MINCLOCK=MINCLOCK),
    r"{WEEKS}{DAYS}{HOURCLOCK}".format(
        WEEKS=OPTSEP(WEEKS), DAYS=OPTSEP(DAYS), HOURCLOCK=HOURCLOCK
    ),
    r"{DAYCLOCK}".format(DAYCLOCK=DAYCLOCK),
    r"{SECCLOCK}".format(SECCLOCK=SECCLOCK),
]

COMPILED_SIGN = re.compile(r"^\s*" + SIGN + r"\s*(?P<unsigned>.*)$")
COMPILED_TIMEFORMATS = [
    re.compile(r"^\s*" + timefmt + r"\s*$", re.I) for timefmt in TIMEFORMATS
]


class TimeComplex:
    def __init__(self, months, seconds=0):
        self.months = months
        self.seconds = seconds

    def __add__(self, other):
        if isinstance(other, self.__class__):
            return self.__class__(
                self.months + other.months, self.seconds + other.seconds
            )
        return self.__class__(self.months, self.seconds + other)

    def __mul__(self, other):
        return self.__class__(self.months * other, self.seconds * other)

    def __repr__(self):
        return f"{self.__class__.__name__}(months={self.months}, seconds={self.seconds})"

    def get_seconds(self):
        now = datetime.now()
        total_months = now.month + self.months
        then = datetime(
            year=now.year + total_months // 12,
            month=total_months % 12 + 1,
            day=1,
        ) - timedelta(days=1)
        return (
            int(
                (
                    now.replace(
                        year=then.year,
                        month=then.month,
                        day=min(now.day, then.day),
                    )
                    - now
                ).total_seconds()
            )
            + self.seconds
        )


MULTIPLIERS = {
    "years": TimeComplex(12),
    "months": TimeComplex(1),
    "weeks": 60 * 60 * 24 * 7,
    "days": 60 * 60 * 24,
    "hours": 60 * 60,
    "mins": 60,
    "secs": 1,
}


def _interpret_as_minutes(sval, mdict):
    """
    Times like "1:22" are ambiguous; do they represent minutes and seconds
    or hours and minutes?  By default, timeparse assumes the latter.  Call
    this function after parsing out a dictionary to change that assumption.

    >>> import pprint
    >>> pprint.pprint(_interpret_as_minutes('1:24', {'secs': '24', 'mins': '1'}))
    {'hours': '1', 'mins': '24'}
    """
    keys = {k for k, v in mdict.items() if v is not None}
    if sval.count(":") == 1 and "." not in sval and keys == {"secs", "mins"}:
        mdict["hours"] = mdict["mins"]
        mdict["mins"] = mdict.pop("secs")
    return mdict


def timeparse(
    sval: str, granularity: Literal["seconds", "minutes"] = "seconds"
) -> int | float | None:
    """
    Parse a time expression, returning it as a number of seconds.  If
    possible, the return value will be an `int`; if this is not
    possible, the return will be a `float`.  Returns `None` if a time
    expression cannot be parsed from the given string.

    Arguments:
    - `sval`: the string value to parse

    >>> timeparse('1:24')
    84
    >>> timeparse(':22')
    22
    >>> timeparse('1 minute, 24 secs')
    84
    >>> timeparse('1m24s')
    84
    >>> timeparse('1.2 minutes')
    72
    >>> timeparse('1.2 seconds')
    1.2

    Time expressions can be signed.

    >>> timeparse('- 1 minute')
    -60
    >>> timeparse('+ 1 minute')
    60

    If granularity is specified as ``minutes``, then ambiguous digits following
    a colon will be interpreted as minutes; otherwise they are considered seconds.

    >>> timeparse('1:30')
    90
    >>> timeparse('1:30', granularity='minutes')
    5400
    """
    match = COMPILED_SIGN.match(sval)
    sign = -1 if match.groupdict()["sign"] == "-" else 1
    sval = match.groupdict()["unsigned"]
    for timefmt in COMPILED_TIMEFORMATS:
        match = timefmt.match(sval)
        if match and match.group(0).strip():
            mdict = match.groupdict()
            if granularity == "minutes":
                mdict = _interpret_as_minutes(sval, mdict)
            secs = mdict.pop("secs") or "0"
            sum_ = TimeComplex(0)
            for k, v in mdict.items():
                if v is None:
                    continue
                if v.isdecimal():
                    v = int(v)
                else:
                    v = float(v)
                sum_ += MULTIPLIERS[k] * v
            if secs.isdecimal():
                # if SECS is an integer number, return an integer
                sum_.seconds = int(sum_.seconds)
                sum_ += int(secs)
            else:
                sum_ += float(secs)
            return (sum_ * sign).get_seconds()
