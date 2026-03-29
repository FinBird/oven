#!/usr/bin/env python3
"""
Export AngelClientLibs.abc to specified directory
"""

import sys
import shutil
from pathlib import Path

# Set project root directory
root = Path(r'c:/Users/admin/oven/oven')
sys.path.insert(0, str(root.resolve()))

# Import required modules
from api import decompile_abc_to_as_files

def main():
    """Main function: Export AngelClientLibs.abc"""
    # Define input and output paths
    abc_path = root / 'fixtures' / 'abc' / 'AngelClientLibs.abc'
    out_dir = Path(r'C:\Users\admin\oven\out\AngelClientLibs')
    
    # Clean and create output directory
    print(f"Cleaning output directory: {out_dir}")
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Execute decompilation
    print(f"Starting export of {abc_path.name}...")
    files = decompile_abc_to_as_files(
        abc_path, 
        out_dir, 
        debug=False,
        style='semantic', 
        int_format='hex', 
        clean_output=True, 
        parallel=True,
        inline_vars=True,
        auto_disable_parallel_in_pypy=True  # 自动在PyPy下禁用并行
    )
    
    print(f"Export completed, {len(files)} files generated")
    print(f"Output directory: {out_dir}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
