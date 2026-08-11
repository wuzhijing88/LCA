from ..parameter_panel_support import *


class ParameterPanelMediaMultiImagePathsResolverMixin:

    def _create_multi_image_path_resolver(self):
        try:
            from tasks.task_utils import get_image_path_resolver

            resolver = get_image_path_resolver()
            images_dir = getattr(self, "images_dir", None)
            if images_dir and os.path.exists(images_dir):
                resolver.add_search_path(images_dir, priority=0)
            return resolver
        except Exception:
            return None

    def _resolve_multi_image_full_path(self, full_path, original_line, resolver):
        if os.path.exists(full_path) or not resolver:
            return full_path
        resolved = resolver.resolve(full_path)
        if resolved:
            logger.debug(f"Resolved multi image path: {original_line} -> {resolved}")
            return resolved
        return full_path
