from ..parameter_panel_support import *


class ParameterPanelParameterCleanupStorageMixin:

    def _cleanup_all_card_parameters(self):
        if not self.current_card_id:
            return
        try:
            main_window = None
            current_widget = self.parent()
            level = 0
            while current_widget and level < 10:
                if hasattr(current_widget, 'cards') or hasattr(current_widget, 'workflow_data'):
                    main_window = current_widget
                    break
                current_widget = current_widget.parent()
                level += 1
            if not main_window:
                logger.debug("未找到主窗口，跳过卡片参数清理")
                return
            card_id = self.current_card_id
            if hasattr(main_window, 'workflow_data') and isinstance(main_window.workflow_data, dict):
                if 'cards' in main_window.workflow_data:
                    cards = main_window.workflow_data['cards']
                    if isinstance(cards, list):
                        for card in cards:
                            if isinstance(card, dict) and card.get('id') == card_id:
                                if 'parameters' in card:
                                    old_param_count = len(card['parameters'])
                                    card['parameters'].clear()
                                    logger.info(f"Cleared {old_param_count} stored parameters for card {card_id}")
                                break
            elif hasattr(main_window, 'cards') and isinstance(main_window.cards, dict):
                if card_id in main_window.cards:
                    card = main_window.cards[card_id]
                    if 'parameters' in card:
                        old_param_count = len(card['parameters'])
                        card['parameters'].clear()
                        logger.info(f"Cleared {old_param_count} stored parameters for card {card_id}")
        except Exception as e:
            logger.debug(f"Non-fatal error during stored parameter cleanup: {e}")

    def _cleanup_workflow_context(self):
        if not self.current_card_id:
            return
        try:
            from task_workflow.workflow_context import get_workflow_context
            context = get_workflow_context()
            card_id = self.current_card_id
            logger.info(f"Start clearing workflow context for card {card_id}")

            cleared_stats = {
                'card_data_keys': 0,
                'ocr_results': 0,
                'image_results': False,
            }

            self._cleanup_context_card_data(context, card_id, cleared_stats)
            self._cleanup_context_ocr_results(context, card_id, cleared_stats)
            self._cleanup_context_image_results(context, card_id, cleared_stats)
            self._log_context_cleanup_result(context, card_id, cleared_stats)
        except Exception as e:
            logger.error(f"工作流上下文清理失败：{e}", exc_info=True)

    def _cleanup_context_card_data(self, context, card_id: int, cleared_stats: Dict[str, Any]) -> None:
        if card_id not in context.card_data:
            return
        card_data = context.card_data[card_id]
        cleared_stats['card_data_keys'] = len(card_data)
        card_data_keys = list(card_data.keys())
        logger.info(f"Card {card_id} card_data keys: {card_data_keys}")
        function_related_keys = [k for k in card_data_keys if any(kw in k.lower() for kw in ['multi', 'group', 'function', 'state', 'index'])]
        if function_related_keys:
            logger.info(f"Detected multi-function related keys: {function_related_keys}")
        del context.card_data[card_id]
        logger.info(f"Removed context.card_data for card {card_id}, total keys: {len(card_data_keys)}")

    def _cleanup_context_ocr_results(self, context, card_id: int, cleared_stats: Dict[str, Any]) -> None:
        if card_id not in context.ocr_results:
            return
        cleared_stats['ocr_results'] = len(context.ocr_results[card_id])
        del context.ocr_results[card_id]
        logger.info(f"Removed context.ocr_results for card {card_id}, count: {cleared_stats['ocr_results']}")

    def _cleanup_context_image_results(self, context, card_id: int, cleared_stats: Dict[str, Any]) -> None:
        if card_id not in context.image_results:
            return
        cleared_stats['image_results'] = True
        del context.image_results[card_id]
        logger.info(f"Removed context.image_results for card {card_id}")

    def _log_context_cleanup_result(self, context, card_id: int, cleared_stats: Dict[str, Any]) -> None:
        all_cleared = (
            card_id not in context.card_data and
            card_id not in context.ocr_results and
            card_id not in context.image_results
        )
        if all_cleared:
            cleared_summary = []
            if cleared_stats['card_data_keys'] > 0:
                cleared_summary.append(f"card_data({cleared_stats['card_data_keys']} keys)")
            if cleared_stats['ocr_results'] > 0:
                cleared_summary.append(f"ocr_results({cleared_stats['ocr_results']} items)")
            if cleared_stats['image_results']:
                cleared_summary.append("image_results")
            if cleared_summary:
                logger.info(f"Context cleanup verified for card {card_id}: {', '.join(cleared_summary)}")
            else:
                logger.info(f"Card {card_id} has no context data to clear")
            return
        remaining = []
        if card_id in context.card_data:
            remaining_keys = list(context.card_data[card_id].keys())
            remaining.append(f"card_data({remaining_keys})")
        if card_id in context.ocr_results:
            remaining.append(f"ocr_results({len(context.ocr_results[card_id])})")
        if card_id in context.image_results:
            remaining.append("image_results")
        logger.warning(f"Context cleanup incomplete for card {card_id}: {remaining}")
