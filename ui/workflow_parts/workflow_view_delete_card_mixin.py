from .workflow_view_common import *
from ..system_parts.message_box_translator import show_critical_box


class WorkflowViewDeleteCardMixin:

    def delete_card(self, card_id: int, defer_view_refresh: bool = False):
        """Deletes the specified card and its connections from the view - 增强安全版本"""
        debug_print(f"--- [DELETE_CARD_DEBUG] START delete_card for ID: {card_id} ---")
        old_container_id = None
        deleted_is_start_card = False

        # 注释已清理（原注释编码损坏）
        if card_id in self._deleting_cards:
            debug_print(f"  [DELETE_CARD_DEBUG] Card {card_id} is already being deleted, skipping")
            return

        # 直接删除卡片
        logger.info(f"删除卡片: {card_id}")

        # 检查是否正在运行，如果是则阻止删除
        if self._block_edit_if_running("删除卡片"):
            return

        # BUG FIX: 添加到删除集合，防止重复删除
        self._deleting_cards.add(card_id)

        # 设置删除卡片标志，防止连线删除触发额外撤销
        self._deleting_card = True
        debug_print(f"  [UNDO] Set _deleting_card flag to True")

        # 注释已清理（原注释编码损坏）
        # 注释已清理（原注释编码损坏）
        # 注释已清理（原注释编码损坏）
        try:
            # 获取和验证卡片
            card_to_delete = self.cards.get(card_id)
            if not card_to_delete:
                logger.warning(f"尝试删除不存在的卡片 ID: {card_id}")
                debug_print(f"  [错误] 在 self.cards 中未找到卡片 {card_id}")
                return

            debug_print(f"  Card to delete: {card_to_delete}")

            if not hasattr(card_to_delete, 'card_id'):
                logger.error(f"卡片对象缺少card_id属性: {card_to_delete}")
                debug_print("  [错误] 卡片对象缺少 card_id 属性")
                return

            old_container_id = getattr(card_to_delete, "container_id", None)
            deleted_is_start_card = self._is_start_task_type(getattr(card_to_delete, "task_type", ""))
            if getattr(card_to_delete, "is_container_card", False):
                for child in self._get_container_children(card_id):
                    child.set_container_id(None)
                    try:
                        if child.zValue() < 0:
                            child.setZValue(0)
                    except RuntimeError:
                        pass

            # 注释已清理（原注释编码损坏）
            self._save_card_state_for_undo(card_to_delete)

            # --- 使用新的安全清理方法 ---
            self.safe_cleanup_card_state(card_id)

            # --- 清理工作流上下文数据，防止崩溃 ---
            debug_print(f"  Cleaning workflow context data for card {card_id}...")
            try:
                from task_workflow.workflow_context import clear_card_runtime_data, clear_card_vars
                clear_card_runtime_data(card_id)
                clear_card_vars(card_id)
                debug_print(f"    Successfully cleaned workflow context for card {card_id}")
            except Exception as context_e:
                debug_print(f"    清理工作流上下文失败：{context_e}")
                logger.warning(f"清理卡片 {card_id} 工作流上下文失败: {context_e}")

            # --- 清理其他卡片中指向被删除卡片的跳转参数 ---
            debug_print(f"  Cleaning jump target parameters pointing to card {card_id}...")
            self._cleanup_jump_target_references(card_id)

            # 注释已清理（原注释编码损坏）
            debug_print(f"  Starting ENHANCED connection cleanup...")
            # BUG FIX: 使用集合自动去重，避免重复删除导致闪退
            connections_to_remove_set = set()

            # BUG FIX #6: 优化连接收集，避免重复遍历场景
            # 优先从卡片的连接列表收集（最可靠）
            try:
                if hasattr(card_to_delete, 'connections') and card_to_delete.connections:
                    for conn in list(card_to_delete.connections):
                        if conn and id(conn) not in {id(c) for c in connections_to_remove_set}:
                            connections_to_remove_set.add(conn)
                            debug_print(f"    Found connection from card.connections: {conn}")
            except Exception as e:
                debug_print(f"    [WARNING] Error collecting connections from card: {e}")
                logger.warning(f"收集卡片连接时出错: {e}")

            # 从视图的连接列表收集（作为补充，处理可能遗漏的连接）
            try:
                for conn in list(self.connections):
                    if (isinstance(conn, ConnectionLine) and
                        hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                        (conn.start_item == card_to_delete or conn.end_item == card_to_delete)):
                        if conn and id(conn) not in {id(c) for c in connections_to_remove_set}:
                            connections_to_remove_set.add(conn)
                            debug_print(f"    Found connection from view.connections: {conn}")
            except Exception as e:
                debug_print(f"    [WARNING] Error collecting connections from view: {e}")
                logger.warning(f"收集视图连接时出错: {e}")

            # BUG FIX #6: 移除场景遍历，因为前两步已经收集了所有连接
            # BUG FIX #6: 移除场景遍历，因为前两步已经收集了所有连接
            if not connections_to_remove_set:
                debug_print(f"    [WARNING] No connections found in card/view lists, falling back to scene scan")
                try:
                    # 注释已清理（原注释编码损坏）
                    for item in self.scene.items():
                        if (isinstance(item, ConnectionLine) and
                            hasattr(item, 'start_item') and hasattr(item, 'end_item') and
                            (item.start_item == card_to_delete or item.end_item == card_to_delete)):
                            connections_to_remove_set.add(item)
                            debug_print(f"    Found connection from scene fallback: {item}")
                except Exception as e:
                    debug_print(f"    [WARNING] Error in scene fallback scan: {e}")
                    logger.warning(f"场景扫描失败: {e}")

            # 转换为列表进行遍历
            connections_to_remove = list(connections_to_remove_set)
            debug_print(f"  Total connections to remove: {len(connections_to_remove)}")
            logger.debug(f"[DELETE] 需要移除的连接数: {len(connections_to_remove)}")

            # 【调试】记录每个连接的详细信息
            for i, conn in enumerate(connections_to_remove):
                try:
                    start_id = conn.start_item.card_id if conn.start_item else "None"
                    end_id = conn.end_item.card_id if conn.end_item else "None"
                    logger.debug(f"[DELETE] 连接 {i+1}: {start_id} -> {end_id} ({conn.line_type})")
                except:
                    logger.debug(f"[DELETE] 连接 {i+1}: 无法获取信息")

            # 注释已清理（原注释编码损坏）
            # 杩欑‘保动画定时器不会在删除过程中访问这些连接
            try:
                from ..workflow_parts.connection_line import _unregister_animated_line
                for connection in connections_to_remove:
                    _unregister_animated_line(connection)
                    logger.debug(f"[DELETE] 已从全局动画列表预先移除连接")
            except Exception as e:
                logger.warning(f"[DELETE] 预先移除动画列表失败: {e}")

            # 逐个彻底移除连接
            for i, connection in enumerate(connections_to_remove):
                debug_print(f"    [CONN_REMOVE {i+1}/{len(connections_to_remove)}] Processing: {connection}")
                logger.debug(f"[DELETE] 移除连接 {i+1}/{len(connections_to_remove)}...")
                try:
                    # 注释已清理（原注释编码损坏）
                    if connection is None:
                        logger.warning(f"[DELETE] 连接对象为None，跳过")
                        continue

                    # 【关键修复】先保存卡片引用，再清理
                    # 因为cleanup()会将start_item和end_item设为None
                    saved_start_item = getattr(connection, 'start_item', None)
                    saved_end_item = getattr(connection, 'end_item', None)

                    # 【关键修复】先从卡片的连接列表中移除，再调用cleanup
                    # 这样可以确保卡片不再持有对连接的引用
                    try:
                        if saved_start_item:
                            try:
                                _ = saved_start_item.card_id  # 验证卡片有效性
                                if hasattr(saved_start_item, 'connections') and connection in saved_start_item.connections:
                                    debug_print(f"      Removing from start card {saved_start_item.card_id}...")
                                    saved_start_item.connections.remove(connection)
                                    debug_print(f"      Removed from start card. Card connections count: {len(saved_start_item.connections)}")
                            except RuntimeError:
                                logger.warning(f"[DELETE] 起始卡片对象已无效")
                    except Exception as start_e:
                        logger.warning(f"[DELETE] 从起始卡片移除连接失败: {start_e}")

                    try:
                        if saved_end_item:
                            try:
                                _ = saved_end_item.card_id  # 验证卡片有效性
                                if hasattr(saved_end_item, 'connections') and connection in saved_end_item.connections:
                                    debug_print(f"      Removing from end card {saved_end_item.card_id}...")
                                    saved_end_item.connections.remove(connection)
                                    debug_print(f"      Removed from end card. Card connections count: {len(saved_end_item.connections)}")
                            except RuntimeError:
                                logger.warning(f"[DELETE] 目标卡片对象已无效")
                    except Exception as end_e:
                        logger.warning(f"[DELETE] 从目标卡片移除连接失败: {end_e}")

                    # 注释已清理（原注释编码损坏）
                    if connection in self.connections:
                        debug_print(f"      Removing from view connections list...")
                        self.connections.remove(connection)
                        debug_print(f"      Removed from view list. Current count: {len(self.connections)}")

                    # 调用连接线的清理方法（清除内部引用）
                    if hasattr(connection, 'cleanup'):
                        debug_print(f"      Calling connection.cleanup()...")
                        try:
                            connection.cleanup()
                        except RuntimeError:
                            logger.warning(f"[DELETE] 连接cleanup时对象已无效")

                    # 注释已清理（原注释编码损坏）
                    try:
                        conn_valid = True
                        try:
                            from shiboken6 import isValid
                            conn_valid = isValid(connection)
                        except ImportError:
                            pass

                        if conn_valid and hasattr(connection, 'scene'):
                            try:
                                conn_scene = connection.scene()
                            except RuntimeError:
                                conn_scene = None

                            if conn_scene == self.scene:
                                # 【关键修复】在移除前禁用悬停事件和取消选中
                                # 注释已清理（原注释编码损坏）
                                try:
                                    connection.setAcceptHoverEvents(False)
                                    connection.setSelected(False)
                                    connection.setEnabled(False)
                                except (RuntimeError, AttributeError):
                                    pass
                                debug_print(f"      Removing from scene...")
                                self.scene.removeItem(connection)
                                debug_print(f"      Removed from scene")
                    except RuntimeError:
                        logger.warning(f"[DELETE] 从场景移除连接时对象已无效")

                    debug_print(f"      Connection {connection} removed and marked for garbage collection")

                except RuntimeError as re:
                    logger.warning(f"[DELETE] 移除连接时RuntimeError (对象可能已删除): {re}")
                except Exception as e:
                    debug_print(f"    移除连线时发生错误 {connection}：{e}")
                    logger.exception(f"[DELETE] 移除连接时错误: {e}")

            logger.debug(f"[DELETE] 所有连接移除完成")

            # 注释已清理（原注释编码损坏）
            try:
                self.scene.update()
            except Exception:
                pass

            # 【关键修复】强制处理Qt事件队列，确保所有与被删除连接相关的事件都已处理
            # 这防止在事件循环的后续迭代中访问已删除的对象
            if not defer_view_refresh:
                try:
                    QApplication.processEvents()
                except Exception:
                    pass

            # 注释已清理（原注释编码损坏）
            # 使用connections_to_remove集合来确保所有受影响的卡片都被清理
            # 因为此时连接的start_item和end_item可能已被cleanup()清空
            for other_card_id, other_card in self.cards.items():
                if other_card_id == card_id:
                    continue
                if hasattr(other_card, 'connections'):
                    # 直接从connections_to_remove中查找需要移除的连接
                    conns_to_remove_from_card = []
                    for conn in other_card.connections[:]:
                        # 注释已清理（原注释编码损坏）
                        if conn in connections_to_remove_set:
                            conns_to_remove_from_card.append(conn)
                        elif conn is None:
                            conns_to_remove_from_card.append(conn)
                        elif not hasattr(conn, 'scene'):
                            conns_to_remove_from_card.append(conn)
                        else:
                            try:
                                if conn.scene() is None:
                                    conns_to_remove_from_card.append(conn)
                            except RuntimeError:
                                conns_to_remove_from_card.append(conn)

                    if conns_to_remove_from_card:
                        logger.debug(f"[DELETE] 卡片 {other_card_id} 持有 {len(conns_to_remove_from_card)} 个需清理的连接引用")
                        for inv_conn in conns_to_remove_from_card:
                            try:
                                if inv_conn in other_card.connections:
                                    other_card.connections.remove(inv_conn)
                                    logger.debug(f"[DELETE] 已从卡片 {other_card_id} 移除无效连接引用")
                            except (ValueError, RuntimeError, TypeError):
                                pass

            # 娓呯┖要删除卡片的连接列表
            if hasattr(card_to_delete, 'connections'):
                card_to_delete.connections.clear()
                debug_print(f"  Cleared card {card_id} connections list")

            # 验证连接清理结果
            debug_print(f"  Verifying connection cleanup...")
            remaining_invalid = []
            for conn in list(self.connections):  # 使用 list() 创建副本以安全遍历
                try:
                    if (isinstance(conn, ConnectionLine) and
                        ((hasattr(conn, 'start_item') and conn.start_item == card_to_delete) or
                         (hasattr(conn, 'end_item') and conn.end_item == card_to_delete))):
                        remaining_invalid.append(conn)
                except RuntimeError:
                    # 对象已被删除，跳过
                    remaining_invalid.append(conn)

            if remaining_invalid:
                debug_print(f"  WARNING: Found {len(remaining_invalid)} invalid connections still in view list!")
                for conn in remaining_invalid:
                    try:
                        if conn in self.connections:
                            self.connections.remove(conn)
                        debug_print(f"    Force removed: {conn}")
                    except (ValueError, RuntimeError):
                        pass
            else:
                debug_print(f"  Connection cleanup verification PASSED")
            
            # 注释已清理（原注释编码损坏）
            debug_print(f"  Removing card {card_id} from internal dictionary...")
            logger.debug(f"[DELETE] 从字典移除卡片 {card_id}...")
            if card_id in self.cards:
                self.cards.pop(card_id)
                debug_print(f"    Card removed from dictionary. Remaining cards: {len(self.cards)}")
                logger.debug(f"[DELETE] 卡片已从字典移除。剩余: {len(self.cards)}")

            # 注释已清理（原注释编码损坏）
            # 之前的顺序可能导致信号处理器访问正在删除的对象
            from PySide6.QtCore import QTimer

            # 【关键修复】在移除卡片之前停止所有定时器
            # 注释已清理（原注释编码损坏）
            try:
                timer_names = ['flash_toggle_timer', 'selection_flash_timer', '_drag_check_timer', '_hover_timer']
                for timer_name in timer_names:
                    if hasattr(card_to_delete, timer_name):
                        try:
                            timer = getattr(card_to_delete, timer_name)
                            if timer and hasattr(timer, 'stop'):
                                timer.stop()
                                # 断开定时器的所有信号连接
                                if hasattr(timer, 'timeout'):
                                    try:
                                        timer.timeout.disconnect()
                                    except (RuntimeError, TypeError):
                                        pass
                        except (RuntimeError, AttributeError):
                            pass
                logger.debug(f"[DELETE] 已停止卡片所有定时器")
            except Exception as timer_e:
                logger.warning(f"[DELETE] 停止定时器时出错: {timer_e}")

            # 注释已清理（原注释编码损坏）
            debug_print(f"  Removing card from scene immediately...")
            logger.debug(f"[DELETE] 从场景移除卡片...")
            try:
                if card_to_delete:
                    # 注释已清理（原注释编码损坏）
                    card_valid = True
                    try:
                        from shiboken6 import isValid
                        card_valid = isValid(card_to_delete)
                    except ImportError:
                        pass

                    if card_valid:
                        try:
                            card_scene = card_to_delete.scene()
                        except RuntimeError:
                            card_scene = None

                        if card_scene == self.scene:
                            # 【关键修复】在移除前禁用悬停事件和取消选中
                            # 注释已清理（原注释编码损坏）
                            try:
                                card_to_delete.setAcceptHoverEvents(False)
                                card_to_delete.setSelected(False)
                                card_to_delete.setEnabled(False)
                            except (RuntimeError, AttributeError):
                                pass
                            self.scene.removeItem(card_to_delete)
                    debug_print(f"    Card removed from scene.")
                    logger.debug(f"[DELETE] 卡片已从场景移除")
                    # 不调用 deleteLater()，从场景移除后让Python垃圾回收处理
                    # deleteLater() 可能导致在对象被调度删除前，动画定时器仍访问它
                else:
                    logger.debug(f"[DELETE] 卡片不在场景中，跳过removeItem")
            except RuntimeError as scene_e:
                logger.warning(f"[DELETE] 从场景移除卡片时对象已无效: {scene_e}")

            # 发出删除信号 - 移到场景移除之后
            logger.debug(f"[DELETE] 发送card_deleted信号...")
            self.card_deleted.emit(card_id)
            logger.debug(f"[DELETE] 信号已发送")

            # 清理卡片对象引用
            logger.debug(f"[DELETE] 清理卡片引用...")
            try:
                if card_to_delete:
                    if hasattr(card_to_delete, 'view'):
                        card_to_delete.view = None
                    if hasattr(card_to_delete, 'task_module'):
                        card_to_delete.task_module = None
                    if hasattr(card_to_delete, 'parameters'):
                        card_to_delete.parameters.clear()
                    logger.debug(f"[DELETE] 卡片引用已清理")
            except RuntimeError as ref_e:
                logger.warning(f"[DELETE] 清理卡片引用时对象已无效: {ref_e}")
            except Exception as ref_e:
                debug_print(f"    [REF_CLEANUP] 清理卡片引用时出错: {ref_e}")
                logger.warning(f"[DELETE] 清理卡片引用时出错: {ref_e}")

            # 注释已清理（原注释编码损坏）
            # QTimer.singleShot 的 lambda 会捕获 card_to_delete 引用
            # 注释已清理（原注释编码损坏）
            logger.debug(f"[DELETE] 直接完成卡片清理（不使用延迟删除）...")
            try:
                # 注释已清理（原注释编码损坏）
                timer_names = ['flash_toggle_timer', 'selection_flash_timer', '_drag_check_timer', '_hover_timer']
                for timer_name in timer_names:
                    if hasattr(card_to_delete, timer_name):
                        try:
                            timer = getattr(card_to_delete, timer_name)
                            if timer and hasattr(timer, 'stop'):
                                timer.stop()
                                logger.debug(f"[DELETE] 已停止定时器: {timer_name}")
                        except (RuntimeError, AttributeError):
                            pass

                # 注释已清理（原注释编码损坏）
                signal_names = ['delete_requested', 'copy_requested', 'edit_settings_requested',
                                'jump_target_parameter_changed', 'card_clicked', 'position_changed']
                for signal_name in signal_names:
                    if hasattr(card_to_delete, signal_name):
                        try:
                            signal = getattr(card_to_delete, signal_name)
                            signal.disconnect()
                        except (RuntimeError, TypeError):
                            pass

                # 娓呯┖连接列表
                if hasattr(card_to_delete, 'connections'):
                    card_to_delete.connections.clear()

                logger.debug(f"[DELETE] 卡片信号已断开")
            except RuntimeError:
                logger.debug(f"[DELETE] 卡片对象已无效")
            except Exception as e:
                logger.warning(f"[DELETE] 清理卡片时出错: {e}")

            # 【关键修复】强制处理所有挂起的Qt事件
            # 【关键修复】强制处理所有挂起的Qt事件
            if not defer_view_refresh:
                try:
                    QApplication.processEvents()
                except Exception:
                    pass

            # 【关键修复】强制处理Qt事件队列，确保所有与被删除连接相关的事件都已处理
            # 将connections_to_remove中的对象完全清空，防止任何残留引用
            try:
                connections_to_remove.clear()
                connections_to_remove_set.clear()
            except Exception:
                pass

            # 注释已清理（原注释编码损坏）
            card_to_delete = None

            # 注释已清理（原注释编码损坏）
            if not defer_view_refresh:
                try:
                    QApplication.processEvents()
                except Exception:
                    pass

            # 更新序列显示
            logger.debug(f"[DELETE] 更新序列显示...")
            if defer_view_refresh:
                logger.debug(f"[DELETE] Defer sequence refresh: card_id={card_id}")
            else:
                self.update_card_sequence_display()
                if deleted_is_start_card:
                    self._refresh_thread_start_custom_names()
                debug_print(f"  Sequence display updated")
            logger.debug(f"[DELETE] 序列显示更新完成")

            debug_print(f"  [CLEANUP] 跳过手动垃圾回收（由Qt管理）")
            logger.debug(f"[DELETE] 删除流程主体完成")

        except Exception as e:
            # 注释已清理（原注释编码损坏）
            error_msg = f"删除卡片 {card_id} 时发生严重错误: {str(e)}"
            logger.error(error_msg, exc_info=True)
            debug_print(f"  [严重错误] {error_msg}")

            # 【修复】异常发生时也要尝试从场景移除卡片，防止"卡片卡在那里"
            try:
                if card_to_delete:
                    try:
                        from shiboken6 import isValid
                        if isValid(card_to_delete) and card_to_delete.scene() == self.scene:
                            self.scene.removeItem(card_to_delete)
                            logger.debug(f"[DELETE] 异常后从场景移除卡片成功")
                    except ImportError:
                        if card_to_delete.scene() == self.scene:
                            self.scene.removeItem(card_to_delete)
            except:
                pass

            # 显示错误对话框
            show_critical_box(
                self,
                "删除失败",
                f"删除卡片时发生错误:\n{str(e)}\n\n程序状态可能不一致，建议保存工作并重启程序。",
            )
        finally:
            # BUG FIX #5: 移除 finally 中的 gc 操作，已在正常流程中处理
            # 重置删除卡片标志
            self._deleting_card = False
            debug_print(f"  [UNDO] Reset _deleting_card flag to False")

            # BUG FIX: 从删除集合中移除
            self._deleting_cards.discard(card_id)
            debug_print(f"  [DELETE_CARD_DEBUG] Removed card {card_id} from deleting set")

            self._update_card_render_cache_policy()

        debug_print(f"--- [DELETE_CARD_DEBUG] END delete_card for ID: {card_id} (ENHANCED) ---")
        logger.debug(f"[DELETE] 删除卡片 {card_id} 流程结束")

    def safe_cleanup_card_state(self, card_id: int):
        """安全地清理卡片的所有状态，防止删除时崩溃。"""


        try:
            debug_print(f"  [SAFE_CLEANUP] 开始安全清理卡片 {card_id} 状态...")

            # 1. 从闪烁集合中移除
            if card_id in self.flashing_card_ids:
                self.flashing_card_ids.discard(card_id)
                debug_print(f"    [SAFE_CLEANUP] 从闪烁集合中移除卡片 {card_id}")

            # 2. 获取卡片对象
            card = self.cards.get(card_id)
            if not card:
                debug_print(f"    [SAFE_CLEANUP] 卡片 {card_id} 不存在，跳过状态清理")
                return

            # 3. 停止闪烁
            if hasattr(card, 'stop_flash'):
                try:
                    card.stop_flash()
                    debug_print(f"    [SAFE_CLEANUP] 成功停止卡片 {card_id} 闪烁")
                except Exception as e:
                    debug_print(f"    [SAFE_CLEANUP] 停止卡片 {card_id} 闪烁失败: {e}")

            # 4. 停止定时器 - BUG FIX #2: 增加 flash_toggle_timer 清理
            timer_attrs = ['flash_timer', 'flash_toggle_timer', 'selection_flash_timer', '_hover_timer']
            for timer_attr in timer_attrs:
                if hasattr(card, timer_attr):
                    timer = getattr(card, timer_attr, None)
                    if timer:
                        try:
                            # 注释已清理（原注释编码损坏）
                            if hasattr(timer, 'timeout'):
                                try:
                                    timer.timeout.disconnect()
                                except:
                                    pass
                            timer.stop()
                            if hasattr(timer, 'deleteLater'):
                                timer.deleteLater()
                            setattr(card, timer_attr, None)
                            debug_print(f"    [SAFE_CLEANUP] 停止并清理定时器: {timer_attr}")
                        except Exception as e:
                            debug_print(f"    [SAFE_CLEANUP] 停止定时器 {timer_attr} 失败: {e}")

            # 注释已清理（原注释编码损坏）
            if hasattr(card, 'set_execution_state'):
                try:
                    card.set_execution_state('idle')
                    debug_print(f"    [SAFE_CLEANUP] 重置卡片 {card_id} 执行状态")
                except Exception as e:
                    debug_print(f"    [SAFE_CLEANUP] 重置执行状态失败: {e}")

            # 6. BUG FIX: 只断开与此视图相关的信号连接，避免影响其他订阅者
            signal_handlers = [
                ('delete_requested', self.delete_card),
                ('copy_requested', self.handle_copy_card),
                ('edit_settings_requested', None),  # 这个由main_window处理，不在这里断开
                ('jump_target_parameter_changed', self._handle_jump_target_change),
                ('card_clicked', self._handle_card_clicked)
            ]

            for signal_name, handler in signal_handlers:
                if hasattr(card, signal_name):
                    signal = getattr(card, signal_name, None)
                    if signal and handler:  # 只断开有处理器的信号
                        try:
                            # 注释已清理（原注释编码损坏）
                            signal.disconnect(handler)
                            debug_print(f"    [SAFE_CLEANUP] 断开信号: {signal_name} -> {handler.__name__}")
                        except (RuntimeError, TypeError) as e:
                            # RuntimeError: 信号未连接; TypeError: 信号类型错误
                            debug_print(f"    [SAFE_CLEANUP] 断开信号 {signal_name} 时跳过: {e}")
                        except Exception as e:
                            debug_print(f"    [SAFE_CLEANUP] 断开信号 {signal_name} 失败: {e}")

            # 7. 清理任何可能的线程或定时器引用
            try:
                # 清理可能的QTimer引用 - 使用安全的属性获取方式
                # 注释已清理（原注释编码损坏）
                timer_attr_names = []
                try:
                    # 注释已清理（原注释编码损坏）
                    for attr_name in list(dir(card)):
                        if 'timer' in attr_name.lower():
                            timer_attr_names.append(attr_name)
                except RuntimeError:
                    # 对象已被Qt删除
                    pass

                for attr_name in timer_attr_names:
                    try:
                        attr_value = getattr(card, attr_name, None)
                        if attr_value and hasattr(attr_value, 'stop'):
                            try:
                                # 先断开信号
                                if hasattr(attr_value, 'timeout'):
                                    try:
                                        attr_value.timeout.disconnect()
                                    except:
                                        pass
                                attr_value.stop()
                                debug_print(f"    [SAFE_CLEANUP] 停止定时器: {attr_name}")
                            except:
                                pass
                        if attr_value and hasattr(attr_value, 'deleteLater'):
                            try:
                                attr_value.deleteLater()
                                setattr(card, attr_name, None)
                                debug_print(f"    [SAFE_CLEANUP] 清理定时器引用: {attr_name}")
                            except:
                                pass
                    except RuntimeError:
                        # 对象已被Qt删除
                        pass
            except Exception as e:
                debug_print(f"    [SAFE_CLEANUP] 清理定时器引用失败: {e}")

            # 【BUG修复】移除processEvents调用
            # 在清理过程中调用processEvents可能导致:
            # 1. 重入问题：处理其他清理相关事件
            # 2. 璁块棶姝ｅ湪琚竻鐞嗙殑对象瀵艰嚧宕╂簝
            debug_print(f"    [SAFE_CLEANUP] 跳过processEvents（避免重入问题）")

            debug_print(f"    [SAFE_CLEANUP] 卡片 {card_id} 状态清理完成")

        except Exception as e:
            debug_print(f"  [SAFE_CLEANUP] 安全清理卡片 {card_id} 状态时发生错误: {e}")
            logger.error(f"安全清理卡片 {card_id} 状态失败: {e}")
