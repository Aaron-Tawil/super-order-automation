import sys
import os
import pandas as pd

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.extraction.vertex_client import read_excel_safe

def convert_excel_to_csv(input_path, output_path):
    print(f"Reading Excel file from: {input_path}")
    try:
        df = read_excel_safe(input_path)
        print("Excel read successfully.")
        
        print(f"Writing CSV to: {output_path}")
        df.to_csv(output_path, index=False)
        print("CSV write successful.")
        
        # Print first few lines of CSV to verify
        print("\n--- CSV PREVIEW ---")
        with open(output_path, 'r', encoding='utf-8') as f:
            for i in range(5):
                print(f.readline().strip())
        print("-------------------")
        
    except Exception as e:
        print(f"Error converting file: {e}")

if __name__ == "__main__":
    input_file = os.path.join(os.path.dirname(__file__), '../tests-data/lastExcel.xlsx')
    output_file = os.path.join(os.path.dirname(__file__), '../tests-data/lastExcel.csv')
    
    convert_excel_to_csv(input_file, output_file)
