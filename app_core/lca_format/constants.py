LCA_MAGIC = b"LCA1"
LCA_FORMAT_VERSION = 1
LCA_FLAGS = 0
DEFAULT_KEY_ID = 1

LCA_HEADER_SIZE = len(LCA_MAGIC) + 2 + 2 + 2 + 12  # magic + ver + flags + key_id + nonce

LCA_EXTENSION = ".lca"
USER_ERROR_INVALID = "无法打开：不是有效的 LCA 工程文件"

LCA_FILE_FILTER = "LCA 工程 (*.lca);;JSON 工作流 (*.json);;所有文件 (*.*)"
LCA_SAVE_FILTER = "LCA 工程 (*.lca)"
