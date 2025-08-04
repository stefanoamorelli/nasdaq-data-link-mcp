#!/usr/bin/env python3

import re
import os
import sys

def fix_long_dict_lines(file_path):
    """Fix long dictionary lines by converting single-line dicts to multi-line format."""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Pattern to match single-line dictionary entries like:
    # {"name": "foo", "description": "bar", "type": "BigInt"}
    pattern = r'(\s+)(\{"name":\s*"[^"]+",\s*"description":\s*"[^"]+",\s*"type":\s*"[^"]+"\})(,?)'
    
    def replace_func(match):
        indent = match.group(1)
        full_dict = match.group(2)
        comma = match.group(3)
        
        # Extract the parts
        dict_match = re.match(r'\{"name":\s*"([^"]+)",\s*"description":\s*"([^"]+)",\s*"type":\s*"([^"]+)"\}', full_dict)
        if not dict_match:
            return match.group(0)  # Return original if no match
        
        name, description, type_value = dict_match.groups()
        
        # Check if this would be too long (approx 88 chars)
        original_line_length = len(indent) + len(full_dict) + len(comma)
        if original_line_length <= 88:
            return match.group(0)  # Keep as is if not too long
        
        # Create multi-line format
        result = f'{indent}{{\n'
        result += f'{indent}    "name": "{name}",\n'
        
        # Handle long descriptions by breaking them
        if len(description) > 60:
            result += f'{indent}    "description": (\n'
            result += f'{indent}        "{description}"\n'
            result += f'{indent}    ),\n'
        else:
            result += f'{indent}    "description": "{description}",\n'
        
        result += f'{indent}    "type": "{type_value}"\n'
        result += f'{indent}}}{comma}'
        
        return result
    
    # Apply the replacement
    new_content = re.sub(pattern, replace_func, content)
    
    # Also fix dictionaries with additional fields like "filterable", "primary_key"
    pattern2 = r'(\s+)(\{"name":\s*"[^"]+",\s*"description":\s*"[^"]+",\s*"type":\s*"[^"]+",\s*(?:"filterable":\s*\w+,?\s*)?(?:"primary_key":\s*\w+,?\s*)?\})(,?)'
    
    def replace_func2(match):
        indent = match.group(1)
        full_dict = match.group(2)
        comma = match.group(3)
        
        # Check if this would be too long
        original_line_length = len(indent) + len(full_dict) + len(comma)
        if original_line_length <= 88:
            return match.group(0)
        
        # Extract all fields from the dictionary
        dict_content = full_dict[1:-1]  # Remove { }
        fields = []
        
        # Simple parsing for key-value pairs
        parts = re.findall(r'"([^"]+)":\s*([^,}]+)', dict_content)
        
        if len(parts) < 3:
            return match.group(0)  # Return original if parsing failed
        
        result = f'{indent}{{\n'
        for i, (key, value) in enumerate(parts):
            if i == len(parts) - 1:  # Last item, no comma
                result += f'{indent}    "{key}": {value}\n'
            else:
                result += f'{indent}    "{key}": {value},\n'
        result += f'{indent}}}{comma}'
        
        return result
    
    new_content = re.sub(pattern2, replace_func2, new_content)
    
    # Write back to file
    with open(file_path, 'w') as f:
        f.write(new_content)
    
    print(f"Fixed dictionary lines in {file_path}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_dict_lines.py <file_path>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)
    
    fix_long_dict_lines(file_path)

if __name__ == "__main__":
    main()