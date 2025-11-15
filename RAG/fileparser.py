import pandas as pd
import os
import re

# Function to clean the text by removing excess whitespace
def clean_text(text):
    if pd.isna(text):
        return ""
    # Replace multiple whitespaces, newlines with single space
    text = re.sub(r'\s+', ' ', str(text))
    # Remove leading/trailing whitespace
    text = text.strip()
    return text

# Function to process the Excel file
def process_excel_file(excel_path, output_dir):
    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    # Read the Excel file
    df = pd.read_excel(excel_path)
    
    # Get column names (first row is the header)
    columns = df.columns.tolist()
    
    # Get state names (start from the second column)
    states = [col for col in columns[1:] if isinstance(col, str) and col.strip()]
    
    # Create a dictionary to store data for each state
    state_data = {state: [] for state in states}
    
    # Process each row
    for _, row in df.iterrows():
        topic = clean_text(row[columns[0]])
        if not topic:  # Skip rows with empty topics
            continue
            
        # Add data for each state
        for state in states:
            state_info = clean_text(row[state])
            if state_info:  # Only add if there's content
                state_data[state].append(f"Topic: {topic}\n\n{state_info}\n\n{'='*50}\n")
    
    # Write data to files
    for state, data in state_data.items():
        if data:  # Only create files for states with data
            # Clean state name for file naming
            state_file_name = re.sub(r'\W+', '_', state.strip())
            file_path = os.path.join(output_dir, f"{state_file_name}12.txt")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"State: {state}\n\n")
                f.write('\n'.join(data))
            
            print(f"Created file for {state}: {file_path}")

# Path to your Excel file
excel_file_path = "SUT12.xlsx"

# Output directory for the text files
output_directory = "state_data"

# Process the Excel file
process_excel_file(excel_file_path, output_directory)
# ```

# To use this script:

# 1. Install the required libraries if you don't have them already:
#    ```
#    pip install pandas openpyxl
#    ```

# 2. Save your Excel data to a file (e.g., "your_excel_file.xlsx")

# 3 . Update the `excel_file_path` variable in the script to point to your Excel file

# 4 . Run the script

# The script will:
# - Create a directory called "state_data" (or whatever you specify in `output_directory`)
# - Generate a separate text file for each state
# - Format each file with the state name at the top, followed by each topic and the state's specific information
# - Add separation between topics for better readability

# Each text file will be named after the state and will contain all the topics and related information for that state, making it suitable for loading into a vector database for RAG applications.