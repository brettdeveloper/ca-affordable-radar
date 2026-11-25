"""Offline regression for HCD's two CSV schemas and missing-county handling."""
import csv
import io
import unittest

from radar.land import FIELDS, land_key, merge_land, parse_land


class HcdLandTest(unittest.TestCase):
    def csv(self, **edits):
        row = dict.fromkeys((header for header, _, _ in FIELDS), "")
        row.update({
            "Parent Case": "SLA0003183",
            "Local Agency": "Los Angeles",
            "City": "los angeles",
            "APN": "4369007900",
            "Address": "11381 West Chalon Road",
            "Date Notice Issued": "11-12-2026",
            "NOA Due Date": "01-10-2027",
            "Parcel Size (Gross Acres)": "0.726",
            "x": "-118.462681900193",
            "y": "34.087671298576",
            **edits,
        })
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        return stream.getvalue().encode()

    def test_current_record_and_ckan_schema(self):
        raw = self.csv().replace(b"Parcel Size (Gross Acres)", b"parcel_size__gross_acres_")
        record, = parse_land(raw, "land_csv")
        self.assertEqual((record["county"], record["notice_date"], record["due_date"]),
                         ("Los Angeles", "2026-11-12", "2027-01-10"))
        self.assertEqual(record["acreage"], "0.726")
        self.assertEqual(len(merge_land([record, record], [])), 1)
        self.assertNotEqual(land_key(record), land_key(dict(record, case="SLA111")))

    def test_county_is_site_location(self):
        raw = self.csv(**{"Local Agency": "Los Angeles", "City": "Carlsbad", "x": "", "y": ""})
        record, = parse_land(raw, "land_csv")
        self.assertEqual((record["county"], record["county_method"]), ("San Diego", "site city"))
        raw = self.csv(**{"City": "Unlocated", "x": "0", "y": "0"})
        record, = parse_land(raw, "land_csv")
        self.assertEqual(record["county"], "")

    def test_missing_columns_raise(self):
        with self.assertRaisesRegex(ValueError, "fields"):
            parse_land(self.csv().replace(b"Date Notice Issued", b"Different"), "land_csv")


if __name__ == "__main__":
    unittest.main()
