from .workflow_view_common import *


class WorkflowViewConnectionValidationMixin:

    def _sync_connections_with_scene(self):
        """
        同步 self.connections 与场景中的实际连线，修复可能出现的状态不一致。

        问题背景：
        当用户拖拽修改连线时，可能出现以下情况导致不同步：
        1. 场景中存在连线但不在 self.connections 中
        2. self.connections 中有连线但已从场景移除
        3. 卡片的 connections 列表与 self.connections 不一致

        该方法会优先尝试修复引用关系，减少误删有效连线。

        【BUG修复】当连线不在场景中但卡片有效时，尝试修复而非删除
        """
        logger.debug("开始同步连线列表...")

        valid_card_ids = set(self.cards.keys())

        # 步骤1：收集场景中所有有效的 ConnectionLine 对象
        scene_connections = set()
        try:
            for item in self.scene.items():
                if isinstance(item, ConnectionLine):
                    # 验证连线的有效性
                    if (hasattr(item, 'start_item') and item.start_item and
                        hasattr(item, 'end_item') and item.end_item and
                        hasattr(item.start_item, 'card_id') and hasattr(item.end_item, 'card_id') and
                        item.start_item.card_id in valid_card_ids and
                        item.end_item.card_id in valid_card_ids):
                        scene_connections.add(item)
        except Exception as e:
            logger.warning(f"遍历场景收集连线时出错: {e}")

        # 步骤2：收集所有卡片中的连线
        card_connections = set()
        try:
            for card in self.cards.values():
                if hasattr(card, 'connections'):
                    for conn in card.connections:
                        if (isinstance(conn, ConnectionLine) and
                            hasattr(conn, 'start_item') and conn.start_item and
                            hasattr(conn, 'end_item') and conn.end_item and
                            conn.start_item.card_id in valid_card_ids and
                            conn.end_item.card_id in valid_card_ids):
                            card_connections.add(conn)
        except Exception as e:
            logger.warning(f"遍历卡片收集连线时出错: {e}")

        # 步骤3：合并所有有效连线
        all_valid_connections = scene_connections | card_connections

        # 步骤4：转换为列表形式的 self.connections
        current_connections = set(self.connections)

        # 记录差异
        missing_in_list = all_valid_connections - current_connections  # 场景/卡片中有但列表中没有
        orphaned_in_list = current_connections - all_valid_connections  # 列表中有但场景/卡片中没有

        sync_needed = False

        # 添加缺失的连线到 self.connections
        if missing_in_list:
            logger.warning(f"[连线同步] 发现 {len(missing_in_list)} 条连线在场景中但不在列表中，正在添加...")
            for conn in missing_in_list:
                self.connections.append(conn)
                try:
                    from ..workflow_parts.connection_line import ensure_line_animation_registered
                    ensure_line_animation_registered(conn)
                except Exception:
                    pass
                logger.debug(f"  添加连线: {conn.start_item.card_id} -> {conn.end_item.card_id} ({conn.line_type})")
            sync_needed = True

        # 【BUG修复】处理孤立的连线（在列表中但不在场景中）- 尝试修复而非直接删除
        if orphaned_in_list:
            logger.warning(f"[连线同步] 发现 {len(orphaned_in_list)} 条孤立连线在列表中但不在场景中，尝试修复...")
            for conn in orphaned_in_list:
                try:
                    # 检查连线的卡片是否仍然有效
                    if (isinstance(conn, ConnectionLine) and
                        hasattr(conn, 'start_item') and conn.start_item and
                        hasattr(conn, 'end_item') and conn.end_item and
                        hasattr(conn.start_item, 'card_id') and hasattr(conn.end_item, 'card_id') and
                        conn.start_item.card_id in valid_card_ids and
                        conn.end_item.card_id in valid_card_ids):
                        # 卡片有效，尝试将连线重新添加到场景
                        if conn.scene() is None:
                            self.scene.addItem(conn)
                            try:
                                from ..workflow_parts.connection_line import ensure_line_animation_registered
                                ensure_line_animation_registered(conn)
                            except Exception:
                                pass
                            conn.update_path()
                            logger.info(f"  修复连线: {conn.start_item.card_id} -> {conn.end_item.card_id} ({conn.line_type})")
                            sync_needed = True
                        elif conn.scene() != self.scene:
                            # 连线在其他场景中，需要移除
                            self.connections.remove(conn)
                            logger.warning(f"  移除在其他场景中的连线: {conn.start_item.card_id} -> {conn.end_item.card_id}")
                            sync_needed = True
                        # 如果 conn.scene() == self.scene，说明它实际上在场景中，只是没被收集到
                        # 这种情况不需要处理
                    else:
                        # 卡片无效，移除连线
                        self.connections.remove(conn)
                        logger.debug(f"  移除无效连线: {getattr(conn, 'start_item', None)} -> {getattr(conn, 'end_item', None)}")
                        sync_needed = True
                except ValueError:
                    pass  # 已经不在列表中
                except Exception as e:
                    logger.warning(f"  处理孤立连线时出错: {e}")

        # 注释已清理（原注释编码损坏）
        seen = set()
        unique_connections = []
        duplicate_connections = []
        for conn in reversed(self.connections):
            # 使用 (start_card_id, end_card_id, line_type) 作为唯一标识
            if (isinstance(conn, ConnectionLine) and
                hasattr(conn, 'start_item') and conn.start_item and
                hasattr(conn, 'end_item') and conn.end_item and
                hasattr(conn, 'line_type')):
                key = (conn.start_item.card_id, conn.end_item.card_id, conn.line_type)
                if key not in seen:
                    seen.add(key)
                    unique_connections.append(conn)
                else:
                    duplicate_connections.append(conn)

        # 恢复原来的顺序
        unique_connections.reverse()

        if len(unique_connections) != len(self.connections):
            duplicates_removed = len(self.connections) - len(unique_connections)
            logger.warning(f"[连线同步] 移除了 {duplicates_removed} 条重复连线")
            for duplicate_conn in duplicate_connections:
                try:
                    self._force_remove_connection(duplicate_conn)
                except Exception as e:
                    logger.debug(f"清理重复连线失败: {e}")
            self.connections = unique_connections
            sync_needed = True

        if sync_needed:
            logger.info(f"[连线同步] 同步完成，当前有 {len(self.connections)} 条有效连线")
        else:
            logger.debug(f"[连线同步] 无需同步，当前有 {len(self.connections)} 条连线")

    def validate_connections(self):
        """验证并清理无效的连接

        【BUG修复】当连线不在场景中但起始和结束卡片都有效时，尝试修复连线而非删除
        这解决了"运行时连线消失"的问题
        """
        logger.debug("开始验证连接完整性...")

        invalid_connections = []
        connections_to_repair = []  # 需要修复的连接（不在场景中但卡片有效）
        valid_card_ids = set(self.cards.keys())

        for conn in list(self.connections):
            is_invalid = False
            needs_repair = False
            reason = ""

            try:
                # 注释已清理（原注释编码损坏）
                if not isinstance(conn, ConnectionLine):
                    is_invalid = True
                    reason = "连接对象类型无效"
                # 注释已清理（原注释编码损坏）
                elif not hasattr(conn, 'start_item') or not conn.start_item:
                    is_invalid = True
                    reason = "缺少起始卡片"
                elif conn.start_item.card_id not in valid_card_ids:
                    is_invalid = True
                    reason = f"起始卡片 {conn.start_item.card_id} 不存在"
                elif conn.start_item.scene() != self.scene:
                    is_invalid = True
                    reason = f"起始卡片 {conn.start_item.card_id} 不在场景中"
                # 注释已清理（原注释编码损坏）
                elif not hasattr(conn, 'end_item') or not conn.end_item:
                    is_invalid = True
                    reason = "缺少目标卡片"
                elif conn.end_item.card_id not in valid_card_ids:
                    is_invalid = True
                    reason = f"目标卡片 {conn.end_item.card_id} 不存在"
                elif conn.end_item.scene() != self.scene:
                    is_invalid = True
                    reason = f"目标卡片 {conn.end_item.card_id} 不在场景中"
                else:
                    special_rule_error = self._validate_special_connection_rule(
                        conn.start_item,
                        conn.end_item,
                        getattr(conn, 'line_type', ''),
                    )
                    if special_rule_error:
                        is_invalid = True
                        reason = special_rule_error
                    elif conn.scene() != self.scene:
                        # 卡片都有效，但连线不在场景中 - 这可能是一个可修复的问题
                        needs_repair = True
                        reason = "连接不在场景中（将尝试修复）"
            except RuntimeError:
                # C++对象已删除
                is_invalid = True
                reason = "连接或卡片C++对象已删除"

            if is_invalid:
                invalid_connections.append((conn, reason))
                logger.warning(f"发现无效连接: {conn} - {reason}")
            elif needs_repair:
                connections_to_repair.append((conn, reason))
                logger.info(f"发现需要修复的连接: {conn} - {reason}")

        # 【BUG修复】首先尝试修复连接
        repaired_count = 0
        for conn, reason in connections_to_repair:
            try:
                # 尝试将连线重新添加到场景中
                if conn.scene() is None:
                    self.scene.addItem(conn)
                    try:
                        from ..workflow_parts.connection_line import ensure_line_animation_registered
                        ensure_line_animation_registered(conn)
                    except Exception:
                        pass
                    conn.update_path()
                    repaired_count += 1
                    logger.info(f"成功修复连接: {conn.start_item.card_id} -> {conn.end_item.card_id} ({conn.line_type})")
                elif conn.scene() != self.scene:
                    # 连线在其他场景中，这是一个真正的问题
                    logger.warning(f"连线在其他场景中，无法修复: {conn}")
                    invalid_connections.append((conn, "连接在其他场景中"))
            except Exception as e:
                logger.warning(f"修复连接时出错: {e}")
                # 修复失败，将其添加到无效连接列表
                invalid_connections.append((conn, f"修复失败: {e}"))

        if repaired_count > 0:
            logger.info(f"成功修复 {repaired_count} 个连接")

        # 清理无效连接
        if invalid_connections:
            logger.info(f"清理 {len(invalid_connections)} 个无效连接...")
            for conn, reason in invalid_connections:
                try:
                    self._force_remove_connection(conn)
                    logger.debug(f"已清理无效连接: {reason}")
                except Exception as e:
                    logger.error(f"清理连接时出错: {e}")

        logger.debug(f"连接验证完成。剩余有效连接: {len(self.connections)}")
        return len(invalid_connections)

    def _force_remove_connection(self, connection):
        """强制移除连接，不依赖连接对象的完整性"""
        logger.debug(f"强制移除连接: {connection}")

        # 从全局动画注册中移除，避免列表与ID索引残留
        try:
            from ..workflow_parts.connection_line import _unregister_animated_line
            _unregister_animated_line(connection)
            logger.debug(f"从全局动画列表移除连接: {connection}")
        except Exception as e:
            logger.debug(f"从动画列表移除连接时出错: {e}")

        # 注释已清理（原注释编码损坏）
        if connection in self.connections:
            self.connections.remove(connection)
        
        # 从场景移除（如果还在场景中）
        try:
            if connection.scene() == self.scene:
                self.scene.removeItem(connection)
        except Exception as e:
            logger.debug(f"从场景移除连接时出错: {e}")
        
        # 注释已清理（原注释编码损坏）
        try:
            if hasattr(connection, 'start_item') and connection.start_item:
                start_card = connection.start_item
                if hasattr(start_card, 'connections') and connection in start_card.connections:
                    start_card.connections.remove(connection)
        except Exception as e:
            logger.debug(f"从起始卡片移除连接时出错: {e}")
        
        try:
            if hasattr(connection, 'end_item') and connection.end_item:
                end_card = connection.end_item
                if hasattr(end_card, 'connections') and connection in end_card.connections:
                    end_card.connections.remove(connection)
        except Exception as e:
            logger.debug(f"从目标卡片移除连接时出错: {e}")
        
        # 清除连接对象引用
        try:
            if hasattr(connection, 'start_item'):
                connection.start_item = None
            if hasattr(connection, 'end_item'):
                connection.end_item = None
        except Exception as e:
            logger.debug(f"清除连接引用时出错: {e}")
        
        # ConnectionLine继承自QGraphicsPathItem，不是QObject，所以没有deleteLater()
        # 连接已从场景和列表中移除，对象会被 Python 垃圾回收
        try:
            # 注释已清理（原注释编码损坏）
            pass
        except Exception as e:
            logger.debug(f"清理连接时出错: {e}")

    def cleanup_orphaned_connections(self):
        """清理孤立的连接（连接到不存在卡片的连接）"""
        logger.debug("开始清理孤立连接...")
        
        # 从场景中查找所有ConnectionLine对象
        scene_connections = []
        for item in self.scene.items():
            if isinstance(item, ConnectionLine):
                scene_connections.append(item)
        
        orphaned_connections = []
        valid_card_ids = set(self.cards.keys())
        
        for conn in scene_connections:
            is_orphaned = False
            
            # 检查是否连接到已删除的卡片
            if (hasattr(conn, 'start_item') and conn.start_item and 
                conn.start_item.card_id not in valid_card_ids):
                is_orphaned = True
            elif (hasattr(conn, 'end_item') and conn.end_item and 
                  conn.end_item.card_id not in valid_card_ids):
                is_orphaned = True
            # 注释已清理（原注释编码损坏）
            elif conn not in self.connections:
                is_orphaned = True
            
            if is_orphaned:
                orphaned_connections.append(conn)
        
        # 清理孤立连接
        if orphaned_connections:
            logger.info(f"发现 {len(orphaned_connections)} 个孤立连接，正在清理...")
            for conn in orphaned_connections:
                try:
                    self._force_remove_connection(conn)
                except Exception as e:
                    logger.error(f"清理孤立连接时出错: {e}")
        
        logger.debug(f"孤立连接清理完成")
        return len(orphaned_connections)
