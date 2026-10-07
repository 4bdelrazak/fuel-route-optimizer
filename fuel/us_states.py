"""US state and territory postal codes accepted by the importer.

The supplied dataset mixes in 620 Canadian rows (AB, BC, ON, QC and friends).
The assignment is USA-only, so the importer rejects anything outside this set and
reports the count, rather than silently placing Canadian truck stops on a US
route.
"""

# fmt: off
US_STATE_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
})
# fmt: on
