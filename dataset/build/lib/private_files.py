"""Which repo paths are private and must never be in git.

Rule (config/repo_rules.csv, committed_data_rule, David 2026-10-23): all raw data is committed;
only private data stays out, i.e. credentials and raw values from the licensed GTAP database.
private_path_patterns lists what that means for a path. S08-H9, S09-H11 and S10-Hlic all call
is_private(), so the three checks cannot drift apart. A missing or changed config row stops the run."""
import csv
import os

RULES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'repo_rules.csv')
IMPLEMENTED = {
    'committed_data_rule': 'all_raw_data_committed_only_private_data_excluded',
    'private_path_patterns': 'credentials_and_gtap_database_values_only',
}
CREDENTIAL_NAMES = {'.netrc', 'id_rsa', 'id_ed25519', 'credentials.json', '.env'}
GTAP_DB_DIRS = tuple(f'gtap{v}/' for v in range(10, 13))
GTAP_VALUE_FILES = ('dataset/reviews/s10r/duty-vs-collections.',)


def load_rules(path=RULES):
    """Return the rule rows. Raise if the file or a row is missing or the value is not the one implemented."""
    if not os.path.exists(path):
        raise RuntimeError(f'{path} is missing; the private-file rule cannot be read')
    with open(path, newline='') as fh:
        rows = {r['choice']: r for r in csv.DictReader(fh)}
    for choice, value in IMPLEMENTED.items():
        row = rows.get(choice)
        if row is None:
            raise RuntimeError(f'{path} has no {choice} row')
        if row['value'] != value or not row['decided_by'].strip() or not row['decided_at'].strip():
            raise RuntimeError(f'{path} {choice}: value {row["value"]!r} is not {value!r}, or decided_by/decided_at is blank')
    return rows


def is_private(path):
    low = path.replace('\\', '/').lower()
    if low.startswith('./'):
        low = low[2:]
    base = os.path.basename(low)
    if base in CREDENTIAL_NAMES or base.endswith('.pem') or '.secrets/' in low:
        return True
    if any(('/' + d) in ('/' + low) for d in GTAP_DB_DIRS):
        return True
    if low.endswith('.har') and not low.startswith('dataset/stages'):
        return True
    return low.startswith(GTAP_VALUE_FILES)


def private_paths(paths):
    load_rules()
    return sorted({p for p in paths if is_private(p)})


if __name__ == '__main__':
    # Self-test: each pattern must catch its example, and committed raw data must pass.
    caught = ['home/box/.secrets/wits.txt', '.netrc', 'Data/GTAP10/basedata.har', 'x/gtap12/sets.har',
              'dataset/reviews/S10R/duty-vs-collections.csv', 'keys/server.pem']
    allowed = ['dataset/data/baci/BACI_HS22_V202601.zip.part00', 'dataset/data/trains_internal/x.tar',
               'docs/gtap_method_sources/GTAP12_ch11B_MAcMap_tariffs.txt', 'dataset/data/gtap_hs_concordance/a.xlsx',
               'dataset/stages/S15_har/output/basedata.har', 'dataset/data/oecd_wto_batis/ebops2022.csv.part00']
    bad = [p for p in caught if not is_private(p)] + [p for p in allowed if is_private(p)]
    load_rules()
    print('ok' if not bad else 'FAIL ' + ' '.join(bad))
    raise SystemExit(1 if bad else 0)
