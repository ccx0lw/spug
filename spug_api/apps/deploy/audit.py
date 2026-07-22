from apps.deploy.models import DeployOperationLog


def format_app_environment_action(action, deploy, target=''):
    """统一生成包含应用和环境的迭代明细操作文案。"""
    if not deploy:
        app_name = env_name = '未知'
    else:
        app_name = deploy.app.name if deploy.app else str(deploy.app_id)
        env_name = deploy.env.name if deploy.env else str(deploy.env_id)
    return f'{action}应用【{app_name}】{target}（环境【{env_name}】）'


def record_deploy_operation(target_type, target_id, target_name, action, operator=None):
    """记录轻量发布审计日志，不保存请求参数或业务数据快照。"""
    if operator:
        operator_name = operator.nickname or operator.username
    else:
        operator_name = '系统'
    return DeployOperationLog.objects.create(
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        action=action,
        operator=operator,
        operator_name=operator_name,
    )
