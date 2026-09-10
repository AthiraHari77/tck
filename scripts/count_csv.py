"""
Count SUCCESS / ERROR rows in a tck_results.csv file.

Usage: python3 scripts/count_csv.py <csv_path>
Output: one line — "<total> <pass> <fail>"

Uses the same csv.reader() logic as parse_csv() in generate_dashboard.py so
the bash-side counts are provably identical to what the dashboard reports,
regardless of quoted commas or escaped double-quotes in the message column.
"""
import csv
import sys


def count(csv_path):
    total = pass_ = fail = 0
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 4:
                continue
            total += 1
            if row[3].strip('"') == "SUCCESS":
                pass_ += 1
            else:
                fail += 1
    return total, pass_, fail


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: count_csv.py <csv_path>", file=sys.stderr)
        sys.exit(1)
    t, p, f = count(sys.argv[1])
    print(t, p, f)
