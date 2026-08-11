from .parameter_panel_media_multi_image_paths_common_mixin import (
    ParameterPanelMediaMultiImagePathsCommonMixin,
)
from .parameter_panel_media_multi_image_paths_resolver_mixin import (
    ParameterPanelMediaMultiImagePathsResolverMixin,
)


class ParameterPanelMediaMultiImagePathsParseCoreMixin(
    ParameterPanelMediaMultiImagePathsCommonMixin,
    ParameterPanelMediaMultiImagePathsResolverMixin,
):

    def _parse_image_paths(self, paths_text: str) -> list:
        lines = self._split_multi_image_path_lines(paths_text)
        if not lines:
            return []

        resolver = self._create_multi_image_path_resolver()
        common_dir = None
        file_paths = []
        for line in lines:
            common_dir_candidate = self._extract_multi_image_common_dir(line)
            if common_dir_candidate is not None:
                common_dir = common_dir_candidate
                continue
            if self._is_multi_image_comment_line(line):
                continue

            full_path = self._convert_multi_image_line_to_full_path(line, common_dir)
            if not self._is_supported_multi_image_path(full_path):
                continue

            full_path = self._resolve_multi_image_full_path(full_path, line, resolver)
            file_paths.append(full_path)
        return file_paths
