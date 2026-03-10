# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.apps import AppConfig
import threading
import logging

logger = logging.getLogger(__name__)


class DeployConfig(AppConfig):
    name = 'apps.deploy'

    def ready(self):
        # 延迟执行启动恢复，确保所有服务（DB、Redis）已就绪
        # 使用 daemon=True 确保不阻止进程退出
        t = threading.Timer(15, self._safe_recover)
        t.daemon = True
        t.start()

    @staticmethod
    def _safe_recover():
        try:
            from apps.deploy.utils import _recover_on_startup
            _recover_on_startup()
        except Exception as e:
            logger.error(f'服务启动恢复迭代发布队列失败: {e}')
