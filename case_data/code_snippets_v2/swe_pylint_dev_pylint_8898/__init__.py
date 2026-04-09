# Licensed under the GPL: https://www.gnu.org/licenses/old-licenses/gpl-2.0.html
# For details: https://github.com/pylint-dev/pylint/blob/main/LICENSE
# Copyright (c) https://github.com/pylint-dev/pylint/blob/main/CONTRIBUTORS.txt

"""Some various utilities and helper classes, most of them used in the
main pylint class.
"""

# [stripped] from pylint.utils.ast_walker import ASTWalker
# [stripped] from pylint.utils.docs import print_full_documentation
# [stripped] from pylint.utils.file_state import FileState
# [stripped] from pylint.utils.linterstats import LinterStats, ModuleStats, merge_stats
# [stripped] from pylint.utils.utils import (
# [stripped]     HAS_ISORT_5,
# [stripped]     IsortDriver,
# [stripped]     _check_csv,
# [stripped]     _splitstrip,
# [stripped]     _unquote,
# [stripped]     decoding_stream,
# [stripped]     diff_string,
# [stripped]     format_section,
# [stripped]     get_module_and_frameid,
# [stripped]     get_rst_section,
# [stripped]     get_rst_title,
# [stripped]     normalize_text,
# [stripped]     register_plugins,
# [stripped]     tokenize_module,
# [stripped] )

__all__ = [
    "ASTWalker",
    "HAS_ISORT_5",
    "IsortDriver",
    "_check_csv",
    "_splitstrip",
    "_unquote",
    "decoding_stream",
    "diff_string",
    "FileState",
    "format_section",
    "get_module_and_frameid",
    "get_rst_section",
    "get_rst_title",
    "normalize_text",
    "register_plugins",
    "tokenize_module",
    "merge_stats",
    "LinterStats",
    "ModuleStats",
    "print_full_documentation",
]
