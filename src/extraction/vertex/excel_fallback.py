import xml.etree.ElementTree as ET
import zipfile

import openpyxl
import pandas as pd

from src.shared.logger import get_logger

logger = get_logger(__name__)


def read_excel_safe(file_path: str) -> pd.DataFrame:
    """
    Robust Excel reader with layered fallbacks for malformed XLSX files.
    """
    try:
        return pd.read_excel(file_path)
    except Exception as e:
        logger.warning(f"Standard pd.read_excel failed: {e}. Attempting fallback with openpyxl...")
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            try:
                ws = wb.active
                data = ws.values
                columns = next(data)
                df = pd.DataFrame(data, columns=columns)
                logger.info("Fallback Excel read successful.")
                return df
            finally:
                wb.close()
        except Exception as fallback_e:
            logger.error(f"Fallback Excel read (openpyxl) failed: {fallback_e}")
            logger.info("Attempting Level 3 Fallback: Raw XML Parsing...")
            try:
                return read_xlsx_via_xml(file_path)
            except Exception as xml_e:
                logger.error(f"Level 3 XML read failed: {xml_e}")
                raise e from xml_e


def read_xlsx_via_xml(file_path: str) -> pd.DataFrame:
    """
    Parses an XLSX by reading the XML files directly, bypassing style validation.
    """
    with zipfile.ZipFile(file_path, "r") as z:
        shared_strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as f:
                tree = ET.parse(f)
                root = tree.getroot()
                for si in root.findall(".//{*}si"):
                    text_nodes = si.findall(".//{*}t")
                    text = "".join(node.text or "" for node in text_nodes)
                    shared_strings.append(text)

        sheet_path = None
        for name in z.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheet_path = name
                break

        if not sheet_path:
            raise ValueError("No worksheet found in XLSX archive")

        logger.info(f"Parsing raw XML from {sheet_path}...")

        data_rows = []
        with z.open(sheet_path) as f:
            context = ET.iterparse(f, events=("end",))
            current_row = []

            for _event, elem in context:
                if elem.tag.endswith("row"):
                    data_rows.append(current_row)
                    current_row = []
                    elem.clear()
                elif elem.tag.endswith("c"):
                    cell_type = elem.get("t")
                    cell_value = None

                    v_node = elem.find(".//{*}v")
                    if v_node is not None and v_node.text:
                        val = v_node.text
                        if cell_type == "s":
                            try:
                                idx = int(val)
                                cell_value = shared_strings[idx] if idx < len(shared_strings) else val
                            except Exception:
                                cell_value = val
                        elif cell_type == "b":
                            cell_value = val == "1"
                        else:
                            try:
                                cell_value = float(val) if "." in val else int(val)
                            except Exception:
                                cell_value = val

                    if cell_value is None and cell_type == "inlineStr":
                        t_node = elem.find(".//{*}is/{*}t")
                        if t_node is not None:
                            cell_value = t_node.text

                    current_row.append(cell_value)

    if not data_rows:
        return pd.DataFrame()

    max_cols = max(len(r) for r in data_rows)
    normalized_data = []
    for row in data_rows:
        padding = [None] * (max_cols - len(row))
        normalized_data.append(row + padding)

    logger.info(f"Level 3 XML extraction successful. Max columns: {max_cols}")

    header_row = normalized_data[0]
    data_body = normalized_data[1:]

    columns = []
    for i, col in enumerate(header_row):
        if col is None:
            columns.append(f"Unnamed: {i}")
        else:
            columns.append(str(col))

    return pd.DataFrame(data_body, columns=columns)
