import pandas as pd
from loguru import logger


class Database:
    """@DynamicAttrs"""
    def __init__(self, db_file='../assets/database/database.xlsx'):
        """Sets each sheet as an attribute and stores the values as a dict of dicts
        Args:
            db_file: Database file in .xlsx format
        """
        self.db_file = db_file
        self.sheet_names = []
        self._load()
        self._custom_parse()

    def _load(self):
        """Loads the database sheets and dynamically sets each sheet as an attribute"""
        # Load database sheets - output of sheets is a list of dicts (each dict = the row's value)
        df = pd.read_excel(self.db_file, sheet_name=None, na_filter=False)
        for sheet_name, values in df.items():
            if 'ports' in sheet_name.split('_')[1:]:
                self._parse_ports(sheet_name, values)
            else:
                self._parse(sheet_name, values)
            self.sheet_names.append(sheet_name)

        logger.debug('Database loaded: {}', self.db_file)

    def _parse(self, sheet, values):
        values = values.to_dict(orient='records')
        first_col = list(values[0].keys())[0]
        parsed = {row[first_col]: row for row in values}
        setattr(self, sheet, parsed)

    def _parse_ports(self, sheet, values):
        setattr(self, sheet, values.to_dict(orient='list'))

    def _custom_parse(self):
        """Post-processing of data that needs further manipulation"""
        # TODO: fix the Raisecoms sheet so it can be handled by parse ports?
        self._split_fields(self.raisecoms)

    def _split_fields(self, sheet):
        """Converts comma separated strings into a list"""
        for values in sheet.values():
            for k, v in values.items():
                split_text = v.split(',')
                if len(split_text) > 1:
                    values[k] = split_text

    def get(self, sheet, col, key):
        """Takes in a key and returns the specified column's value"""
        db_sheet = getattr(self, sheet, None)
        if db_sheet is None:
            error = f"Sheet '{sheet}' doesn't exist"
            raise ValueError(error)

        if db_sheet.get(key) is None:
            error = f"Couldn't find '{key}' in sheet '{sheet}'"
            raise ValueError(error)

        try:
            return db_sheet[key][col]
        except KeyError:
            logger.debug("Invalid column '{}' in sheet '{}'", col, sheet)

    def get_all(self, sheet):
        """Returns a list of all keys for a sheet (first column value), to be used for UI dropdowns"""
        return [k for k, v in getattr(self, sheet).items()]

    def get_hostname(self, ip_addr):
        """Takes in an IP address and returns the corresponding ASR9K router"""
        for host in COMMERCIAL_DB.asr9k_routers.values():
            if host['lo0_ip'] == ip_addr:
                return host['router']

    def headers(self, sheet):
        """Returns a list of sheet headers"""
        sheet_vals = list(getattr(self, sheet).values())
        return list(sheet_vals[0].keys())

    def data(self, sheet):
        """Returns a list of sheet values"""
        sheet_vals = list(getattr(self, sheet).values())
        return [list(row.values()) for row in sheet_vals]


class OhDatabase(Database):
    """@DynamicAttrs"""
    def __init__(self, db_file='../assets/database/oh_database.xlsx'):
        super().__init__(db_file)
        self.db_file = db_file

    def _custom_parse(self):
        pass


COMMERCIAL_DB = Database()
OH_DB = OhDatabase()

def main():
    print(OH_DB.node_vars)


if __name__ == '__main__':
    main()
