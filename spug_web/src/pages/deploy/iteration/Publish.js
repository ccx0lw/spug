/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Card, Row, Col, Tag, Button, Table, Progress, Space, message, Badge, Tooltip, Popover, Alert, Select } from 'antd';
import {
  RocketOutlined, 
  CheckCircleOutlined, 
  CloseCircleOutlined, 
  LoadingOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  PlayCircleOutlined,
  EyeOutlined,
  CloudUploadOutlined,
  SyncOutlined,
  CloudServerOutlined,
  EditOutlined,
  DeleteOutlined,
  InfoCircleOutlined,
  FileTextOutlined
} from '@ant-design/icons';
import { AuthButton } from 'components';
import { http } from 'libs';
import ImageConsole from '../docker/images/Console';
import store from './store';
import S from './index.module.less';

function Publish() {
  const record = store.record;
  const publishStatus = store.publishStatus || [];
  const iterationDetailCount = publishStatus.reduce((sum, env) => sum + env.total, 0);
  const [uploadingEnv, setUploadingEnv] = useState(null);
  const [retryingDetail, setRetryingDetail] = useState(null);
  const [editingVersion, setEditingVersion] = useState(null);  // 正在编辑版本的 detail id
  const [versionOptions, setVersionOptions] = useState({});    // 版本选项缓存 {detailId: versions}
  const [versionLoading, setVersionLoading] = useState(null);  // 正在加载版本的 detail id
  const [removingDetail, setRemovingDetail] = useState(null);
  const [removingEnv, setRemovingEnv] = useState(null);
  const [imageLogRecord, setImageLogRecord] = useState(null);

  // 自动刷新状态
  useEffect(() => {
    if (!store.publishVisible || !record.id) return;

    // 首次加载
    store.fetchPublishStatus(record.id);

    // 设置定时刷新
    const timer = setInterval(() => {
      if (store.publishVisible && record.id) {
        store.fetchPublishStatus(record.id);
      }
    }, 5000); // 每15秒刷新一次

    return () => clearInterval(timer);
  }, [store.publishVisible, record.id]);


  const getWarningColor = (level) => {
    const colors = {
      danger: 'error',
      warning: 'warning',
      info: 'processing',
    };
    return colors[level] || 'default';
  };

  const renderWarningPopover = (warning) => {
    const relatedIterations = warning.related_iterations || [];
    const latestSuccess = warning.latest_success;
    return (
      <div className={S.versionWarningPopover}>
        <div className={S.versionWarningSummary}>{warning.message}</div>
        {latestSuccess && (
          <div className={S.versionWarningSection}>
            <div className={S.versionWarningSectionTitle}>最近成功发布</div>
            <div className={S.versionWarningMeta}>
              <Tag color="success" className={S.versionWarningVersion}>{latestSuccess.version}</Tag>
              {latestSuccess.iteration_name && <span>迭代：{latestSuccess.iteration_name}</span>}
              {latestSuccess.do_at && <span>时间：{latestSuccess.do_at}</span>}
            </div>
          </div>
        )}
        {relatedIterations.length > 0 && (
          <div className={S.versionWarningSection}>
            <div className={S.versionWarningSectionTitle}>相关迭代</div>
            {relatedIterations.map(item => (
              <div
                key={`${item.iteration_id}-${item.version}-${item.request_id || ''}`}
                className={S.versionWarningRelatedItem}>
                <span className={S.versionWarningIterationName}>{item.iteration_name}</span>
                <Tag className={S.versionWarningVersion}>{item.version}</Tag>
                <span>{item.detail_status_alias}</span>
                {item.request_retry_allowed && <Tag color="warning">可重试</Tag>}
              </div>
            ))}
          </div>
        )}
        <div className={S.versionWarningFooter}>仅作提示，不限制继续发布或回滚。</div>
      </div>
    );
  };

  const renderPublishWarnings = (warningDetails) => (
    <div style={{ marginTop: 12 }}>
      <Alert
        type={warningDetails.some(item => item.cross_iteration_warning.level === 'danger') ? 'error' : 'warning'}
        showIcon
        message={`检测到 ${warningDetails.length} 个版本或跨迭代提示`}
        description={
          <div>
            {warningDetails.map(detail => {
              const warning = detail.cross_iteration_warning;
              return (
                <div key={detail.id} className={S.versionWarningConfirmItem}>
                  <span className={S.versionWarningConfirmApp}>{detail.app_name}</span>
                  <Tag color={getWarningColor(warning.level)}>{warning.label}</Tag>
                  <span className={S.versionWarningConfirmMessage}>{warning.message}</span>
                </div>
              );
            })}
            <div style={{ marginTop: 8, color: '#8c8c8c' }}>
              该信息仅用于提示，确认后仍可继续发布或回滚。
            </div>
          </div>
        }
      />
    </div>
  );

  const handlePublish = (envId, envName, isProd) => {
    const envStatus = publishStatus.find(item => Number(item.env_id) === Number(envId));
    const warningDetails = ((envStatus && envStatus.details) || []).filter(detail => (
      detail.status === '0'
      && detail.cross_iteration_warning
      && detail.cross_iteration_warning.has_warning
    ));
    if (isProd || warningDetails.length > 0) {
      Modal.confirm({
        title: isProd ? '生产环境发布确认' : '版本与跨迭代提示',
        icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
        content: (
          <div>
            {isProd && (
              <div>
                <p>您即将发布到 <Tag color="error">{envName}</Tag> (生产环境)</p>
                <p style={{ color: '#ff4d4f' }}>请确认已完成所有测试环境的验证！</p>
              </div>
            )}
            {warningDetails.length > 0 && renderPublishWarnings(warningDetails)}
          </div>
        ),
        okText: warningDetails.length > 0 ? '确认继续发布' : '确认发布',
        okButtonProps: {
          danger: isProd || warningDetails.some(item => item.cross_iteration_warning.level !== 'info'),
        },
        cancelText: '取消',
        onOk: () => doPublish(envId, envName),
      });
    } else {
      doPublish(envId, envName);
    }
  };

  const doPublish = (envId, envName) => {
    store.publishByEnv(record.id, envId)
      .then(res => {
        message.success(`${envName} 环境发布任务已创建`);
      })
      .catch(err => {
        message.error(err.message || '发布失败');
      });
  };

  const showImageLog = (detail) => {
    const envStatus = publishStatus.find(item => (
      (item.details || []).some(envDetail => envDetail.id === detail.id)
    ));
    setImageLogRecord({
      ...detail.docker_image,
      id: detail.docker_image_id,
      app_name: detail.app_name,
      version: detail.version,
      env_name: envStatus ? envStatus.env_name : '',
      env_prod: envStatus ? envStatus.is_prod : false,
    });
  };

  // 预传镜像
  const handlePreUploadImage = (envId, envName, hasContainerApp) => {
    if (!hasContainerApp) {
      message.warning('该环境没有容器镜像类型的应用');
      return;
    }
    setUploadingEnv(envId);
    store.preUploadImage(record.id, envId)
      .then(res => {
        let msg = res.message || `${envName} 环境镜像预上传任务已创建`;
        if (res.failed && res.failed.length > 0) {
          // 有失败的应用，显示警告
          const failedApps = res.failed.map(f => f.app_name).join('、');
          message.warning(`${msg}。失败的应用: ${failedApps}`, 5);
        } else {
          message.success(msg);
        }
      })
      .catch(err => {
        message.error(err.message || '预上传失败');
      })
      .finally(() => {
        setUploadingEnv(null);
      });
  };

  // 单个镜像重试
  const handleRetryImage = (detailId, appName) => {
    setRetryingDetail(detailId);
    store.retryImage(record.id, detailId)
      .then(res => {
        message.success(`${appName} 镜像重新上传任务已创建`);
      })
      .catch(err => {
        message.error(err.message || '重试失败');
      })
      .finally(() => {
        setRetryingDetail(null);
      });
  };

  // 重试发布
  const [retryingPublish, setRetryingPublish] = useState(null);
  const doRetryPublish = (detail) => {
    setRetryingPublish(detail.id);
    return store.retryPublish(detail.id)
      .then(res => {
        message.success(`${detail.app_name} 已重新启动发布`);
      })
      .catch(err => {
        message.error(err.message || '重试发布失败');
      })
      .finally(() => {
        setRetryingPublish(null);
      });
  };

  const handleRetryPublish = (detail) => {
    const warning = detail.cross_iteration_warning;
    if (!warning || !warning.has_warning) {
      doRetryPublish(detail);
      return;
    }
    Modal.confirm({
      title: '重试发布版本提示',
      icon: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
      content: renderPublishWarnings([detail]),
      okText: '确认继续重试',
      okButtonProps: { danger: warning.level !== 'info' },
      cancelText: '取消',
      onOk: () => doRetryPublish(detail),
    });
  };

  // 加载应用版本列表
  const loadVersionOptions = async (detail) => {
    if (versionOptions[detail.id]) {
      setEditingVersion(detail.id);
      return;
    }
    
    setVersionLoading(detail.id);
    try {
      // 直接使用 detail 中的 deploy_id
      const deployId = detail.deploy_id;
      
      if (!deployId) {
        message.warning('未找到部署配置，请检查该应用在该环境是否有发布配置');
        setVersionLoading(null);
        return;
      }

      const response = await http.get(`/api/app/deploy/${deployId}/versions/`);
      const responseData = response.data || response;
      const tags = responseData.tags || {};
      const versionList = Object.entries(tags).map(([name, info]) => ({
        name,
        id: info.id,
        author: info.author,
        date: info.date,
      }));
      
      setVersionOptions(prev => ({ ...prev, [detail.id]: versionList }));
      setEditingVersion(detail.id);
    } catch (error) {
      console.error('获取版本失败:', error);
      message.error('获取版本失败');
    } finally {
      setVersionLoading(null);
    }
  };

  // 更新版本
  const handleUpdateVersion = async (detailId, newVersion) => {
    try {
      await store.updateDetailVersion(detailId, newVersion);
      message.success('版本更新成功');
      setEditingVersion(null);
      store.fetchPublishStatus(record.id);
    } catch (error) {
      message.error(error.message || '更新版本失败');
    }
  };

  const handleRemoveDetail = (detail) => {
    const envStatus = publishStatus.find(
      item => Number(item.env_id) === Number(detail.env_id)
    );
    const envName = envStatus ? envStatus.env_name : '未知环境';
    const isProd = Boolean(envStatus && envStatus.is_prod);
    Modal.confirm({
      title: '移除环境下的应用',
      icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
      content: (
        <div className={S.removeDetailConfirm}>
          <div className={S.removeDetailTarget}>
            <div className={S.removeDetailTargetRow}>
              <span className={S.removeDetailLabel}>发布环境</span>
              <span>
                <Tag color={isProd ? 'error' : 'processing'} className={S.removeDetailEnvTag}>
                  {envName}
                </Tag>
                {isProd && <span className={S.removeDetailProdText}>生产环境</span>}
              </span>
            </div>
            <div className={S.removeDetailTargetRow}>
              <span className={S.removeDetailLabel}>应用</span>
              <strong className={S.removeDetailAppName}>{detail.app_name}</strong>
            </div>
          </div>
        </div>
      ),
      okText: '确认移除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => {
        setRemovingDetail(detail.id);
        return store.removeIterationDetail(detail.id)
          .then(() => {
            message.success(`应用【${detail.app_name}】已从【${envName}】环境移除`);
          })
          .catch(err => {
            message.error(err.message || '移除应用失败');
            return Promise.reject(err);
          })
          .finally(() => {
            setRemovingDetail(null);
          });
      },
    });
  };

  const handleBatchRemoveDetails = (envStatus, removableDetails) => {
    const visibleApps = removableDetails.slice(0, 8);
    const hiddenCount = removableDetails.length - visibleApps.length;
    Modal.confirm({
      title: '批量移除待发布应用',
      icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
      content: (
        <div className={S.removeDetailConfirm}>
          <div className={S.removeDetailTarget}>
            <div className={S.removeDetailTargetRow}>
              <span className={S.removeDetailLabel}>发布环境</span>
              <span>
                <Tag
                  color={envStatus.is_prod ? 'error' : 'processing'}
                  className={S.removeDetailEnvTag}>
                  {envStatus.env_name}
                </Tag>
                {envStatus.is_prod && <span className={S.removeDetailProdText}>生产环境</span>}
              </span>
            </div>
            <div className={S.removeDetailTargetRow}>
              <span className={S.removeDetailLabel}>待移除应用</span>
              <div className={S.removeDetailAppList}>
                {visibleApps.map(detail => (
                  <Tag key={detail.id} className={S.removeDetailAppTag}>
                    {detail.app_name}
                  </Tag>
                ))}
                {hiddenCount > 0 && <span className={S.removeDetailMoreApps}>另有 {hiddenCount} 个</span>}
              </div>
            </div>
          </div>
          <div className={S.removeDetailNotice}>
            <InfoCircleOutlined className={S.removeDetailNoticeIcon} />
            <div>
              <div className={S.removeDetailNoticeTitle}>
                将一次移除 {removableDetails.length} 个待发布应用
              </div>
              <div className={S.removeDetailNoticeText}>
                已预传镜像、已创建发布申请或不处于待发布状态的应用不会被移除。
              </div>
            </div>
          </div>
        </div>
      ),
      okText: `确认移除 ${removableDetails.length} 个`,
      okType: 'danger',
      cancelText: '取消',
      onOk: () => {
        setRemovingEnv(envStatus.env_id);
        return store.removeIterationDetails(record.id, envStatus.env_id)
          .then(res => {
            message.success(res.message || `已移除 ${removableDetails.length} 个应用`);
          })
          .catch(err => {
            message.error(err.message || '批量移除应用失败');
            return Promise.reject(err);
          })
          .finally(() => {
            setRemovingEnv(null);
          });
      },
    });
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case '0': return <ClockCircleOutlined style={{ color: '#1890ff' }} />;
      case '1': return <LoadingOutlined style={{ color: '#faad14' }} spin />;
      case '2': return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case '3': return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
      case '4': return <ExclamationCircleOutlined style={{ color: '#faad14' }} />;
      default: return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />;
    }
  };

  const getStatusTag = (status, statusAlias) => {
    const colors = {
      '0': 'processing',
      '1': 'warning',
      '2': 'success',
      '3': 'error',
      '4': 'warning',
    };
    return <Tag color={colors[status] || 'default'}>{statusAlias || status}</Tag>;
  };

  // 镜像状态显示
  const getImageStatusTag = (imageStatus, isContainer) => {
    if (!isContainer) return null;
    switch (imageStatus) {
      case '0':
        return <Tag color="default"><CloudServerOutlined /> 未上传</Tag>;
      case '1':
        return <Tag color="processing" icon={<SyncOutlined spin />}>上传中</Tag>;
      case '2':
        return <Tag color="success" icon={<CheckCircleOutlined />}>镜像已上传</Tag>;
      case '3':
        return <Tag color="error" icon={<CloseCircleOutlined />}>上传失败</Tag>;
      default:
        return null;
    }
  };

  const detailColumns = [
    {
      title: '应用名称',
      dataIndex: 'app_name',
      width: 180,
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 150,
      render: (text, detail) => {
        // 待发布，或发布失败且仍允许重试时，才允许修改版本。
        const imageStatus = detail.image_status;
        const status = detail.status;
        const isContainer = detail.is_container;
        
        const imageUploading = isContainer && imageStatus === '1';  // 上传中
        const imageUploaded = isContainer && imageStatus === '2';   // 已上传
        const retryableFailure = status === '3'
          && detail.request_id
          && detail.request_retry_allowed;
        const canEditVersion = !imageUploading
          && !imageUploaded
          && (status === '0' || retryableFailure);

        // 正在编辑中
        if (editingVersion === detail.id && canEditVersion) {
          const versions = versionOptions[detail.id] || [];
          return (
            <Space>
              <Select
                size="small"
                style={{ width: 120 }}
                value={text}
                onChange={(val) => handleUpdateVersion(detail.id, val)}
                dropdownMatchSelectWidth={false}
                optionLabelProp="label"
              >
                {versions.map((ver, idx) => (
                  <Select.Option key={idx} value={ver.name} label={ver.name}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontWeight: 500 }}>{ver.name}</span>
                      <span style={{ color: '#999', fontSize: 11 }}>{ver.author} {ver.date}</span>
                    </div>
                  </Select.Option>
                ))}
              </Select>
              <Button size="small" onClick={() => setEditingVersion(null)}>取消</Button>
            </Space>
          );
        }

        // 根据状态生成提示信息
        const getEditTooltip = () => {
          if (imageUploading) return "镜像上传中，无法修改版本";
          if (imageUploaded) return "镜像已上传，无法修改版本";
          return "修改版本";
        };

        return (
          <Space>
            <Tag color="default" style={{ fontFamily: 'monospace' }}>{text}</Tag>
            {canEditVersion && (
              <Tooltip title={getEditTooltip()}>
                <Button
                  type="link"
                  size="small"
                  icon={<EditOutlined />}
                  loading={versionLoading === detail.id}
                  onClick={() => loadVersionOptions(detail)}
                />
              </Tooltip>
            )}
          </Space>
        );
      },
    },
    {
      title: '镜像状态',
      dataIndex: 'image_status',
      width: 130,
      render: (imageStatus, detail) => {
        const isContainer = detail.is_container;
        if (!isContainer) return <span style={{ color: '#999' }}>-</span>;
        return (
          <Space>
            {getImageStatusTag(imageStatus, isContainer)}
            {imageStatus === '3' && (
              <Tooltip title="重新上传镜像">
                <Button
                  type="link"
                  size="small"
                  icon={<SyncOutlined />}
                  loading={retryingDetail === detail.id}
                  onClick={() => handleRetryImage(detail.id, detail.app_name)}
                >
                  重试
                </Button>
              </Tooltip>
            )}
          </Space>
        );
      },
    },
    {
      title: '版本提示',
      dataIndex: 'cross_iteration_warning',
      width: 160,
      render: (warning) => {
        if (!warning || !warning.has_warning) {
          return <span style={{ color: '#bfbfbf' }}>-</span>;
        }
        return (
          <div className={S.versionWarningCell}>
            <Tag
              color={getWarningColor(warning.level)}
              className={S.versionRiskTag}>
              {warning.label}
            </Tag>
            <Popover
              placement="topLeft"
              trigger={['hover', 'click']}
              content={renderWarningPopover(warning)}
            >
              <Button
                type="link"
                size="small"
                className={S.versionWarningDetailButton}>
                详情
              </Button>
            </Popover>
          </div>
        );
      },
    },
    {
      title: '发布状态',
      dataIndex: 'status',
      width: 230,
      render: (status, record) => (
        <Space>
          {getStatusIcon(status)}
          {getStatusTag(status, record.status_alias)}
          {status === '3' && record.request_id && record.request_retry_allowed && (
            <Tooltip title={`可在 ${record.request_retry_deadline} 前重试`}>
              <Button
                type="link"
                size="small"
                icon={<SyncOutlined />}
                loading={retryingPublish === record.id}
                onClick={() => handleRetryPublish(record)}
              >
                重试
              </Button>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '操作',
      dataIndex: 'request_id',
      width: 110,
      render: (requestId, detail) => {
        const canRemove = detail.status === '0'
          && detail.image_status === '0'
          && !detail.docker_image_id
          && !requestId
          && iterationDetailCount > 1;
        const canViewImageLog = Boolean(
          detail.is_container
          && detail.docker_image_id
          && detail.docker_image
        );
        if (!requestId && !canRemove && !canViewImageLog) return '-';
        return (
          <Space size={4}>
            {canViewImageLog && (
              <Tooltip title="查看镜像构建和上传日志">
                <AuthButton
                  auth="deploy.docker_image.view"
                  type="link"
                  size="small"
                  aria-label="查看镜像日志"
                  icon={<FileTextOutlined />}
                  onClick={() => showImageLog(detail)}
                />
              </Tooltip>
            )}
            {requestId && (
              <Tooltip title="查看发布申请">
                <AuthButton
                  auth="deploy.request.view"
                  type="link"
                  size="small"
                  aria-label="查看发布申请"
                  icon={<EyeOutlined />}
                  onClick={() => store.showRequestDetail(requestId)}
                />
              </Tooltip>
            )}
            {canRemove && (
              <Tooltip title="移除未预传镜像且待发布的应用">
                <Button
                  type="link"
                  size="small"
                  danger
                  aria-label="移除应用"
                  icon={<DeleteOutlined />}
                  loading={removingDetail === detail.id}
                  onClick={() => handleRemoveDetail(detail)}
                />
              </Tooltip>
            )}
          </Space>
        );
      },
    },
  ];

  // 计算总体进度
  const totalItems = iterationDetailCount;
  const successItems = publishStatus.reduce((sum, env) => sum + env.success, 0);
  const overallProgress = totalItems > 0 ? Math.round((successItems / totalItems) * 100) : 0;

  return (
    <Modal
      title={
        <Space>
          <RocketOutlined style={{ color: '#1890ff' }} />
          <span>迭代发布 - {record.name}</span>
        </Space>
      }
      visible={store.publishVisible}
      onCancel={() => store.closePublish()}
      footer={[
        <Button key="close" onClick={() => store.closePublish()}>
          关闭
        </Button>,
        <Button key="refresh" type="primary" onClick={() => store.fetchPublishStatus(record.id)}>
          刷新状态
        </Button>,
      ]}
      width={1200}
      bodyStyle={{ padding: '16px 24px', maxHeight: '70vh', overflowY: 'auto' }}
    >
      {/* 总体进度 */}
      <Card size="small" style={{ marginBottom: 16, borderRadius: 8 }}>
        <Row align="middle" gutter={16}>
          <Col span={8}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>总体进度</div>
              <Progress
                type="circle"
                percent={overallProgress}
                width={80}
                format={() => `${successItems}/${totalItems}`}
                strokeColor={{
                  '0%': '#108ee9',
                  '100%': '#87d068',
                }}
              />
            </div>
          </Col>
          <Col span={16}>
            <Row gutter={[16, 8]}>
              <Col span={6}>
                <Badge status="processing" text={`待发布: ${publishStatus.reduce((s, e) => s + e.pending, 0)}`} />
              </Col>
              <Col span={6}>
                <Badge status="warning" text={`发布中: ${publishStatus.reduce((s, e) => s + e.publishing, 0)}`} />
              </Col>
              <Col span={6}>
                <Badge status="success" text={`已成功: ${successItems}`} />
              </Col>
              <Col span={6}>
                <Badge status="error" text={`失败: ${publishStatus.reduce((s, e) => s + e.failed, 0)}`} />
              </Col>
            </Row>
          </Col>
        </Row>
      </Card>

      {/* 按环境显示发布状态 */}
      {publishStatus.map((envStatus, index) => {
        const { env_id, env_name, is_prod, total, pending, publishing, success, failed, details, has_container, image_uploading, image_success, image_failed } = envStatus;
        const envProgress = total > 0 ? Math.round((success / total) * 100) : 0;
        const canPublish = pending > 0 && publishing === 0;
        const isCompleted = success === total;
        const hasContainerApp = has_container || false;
        const canPreUpload = hasContainerApp && pending > 0 && !image_uploading;
        const removableDetails = (details || []).filter(detail => (
          detail.status === '0'
          && detail.image_status === '0'
          && !detail.docker_image_id
          && !detail.request_id
        ));
        const batchRemovalWouldEmptyIteration = (
          removableDetails.length >= iterationDetailCount
        );
        const warningDetails = (details || []).filter(detail => (
          detail.cross_iteration_warning && detail.cross_iteration_warning.has_warning
        ));
        const hasDangerWarning = warningDetails.some(
          detail => detail.cross_iteration_warning.level === 'danger'
        );
        const onlyInfoWarning = warningDetails.length > 0 && warningDetails.every(
          detail => detail.cross_iteration_warning.level === 'info'
        );
        
        return (
          <Card
            key={env_id}
            size="small"
            style={{ 
              marginBottom: 12, 
              borderRadius: 8,
              borderColor: is_prod ? '#ff4d4f' : undefined,
              borderWidth: is_prod ? 2 : 1,
            }}
            title={
              <Space>
                <span style={{ fontWeight: 600, marginRight: 4 }}>{index + 1}.</span>
                {is_prod ? <Tag color="#f50">{env_name}</Tag> : <Tag color="default" style={{ marginRight: 2 }}>{env_name}</Tag>}
                <Progress 
                  percent={envProgress} 
                  size="small" 
                  style={{ width: 100 }}
                  format={() => `${success}/${total}`}
                  status={isCompleted ? 'success' : (failed > 0 ? 'exception' : 'active')}
                />
                {hasContainerApp && (
                  <Tooltip title="该环境包含容器镜像发布">
                    <Tag color="cyan" icon={<CloudServerOutlined />}>容器</Tag>
                  </Tooltip>
                )}
              </Space>
            }
            extra={
              <Space>
                {isCompleted && <Tag color="success" icon={<CheckCircleOutlined />}>已完成</Tag>}
                {publishing > 0 && <Tag color="warning" icon={<LoadingOutlined spin />}>发布中</Tag>}
                {failed > 0 && <Tag color="error">{failed} 个失败</Tag>}
                {removableDetails.length > 1 && (
                  <Tooltip
                    title={batchRemovalWouldEmptyIteration ?
                      '迭代至少需要保留一个应用，不能全部移除' :
                      `批量移除该环境下 ${removableDetails.length} 个未发布应用`}>
                    <span>
                      <Button
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        disabled={batchRemovalWouldEmptyIteration}
                        loading={removingEnv === env_id}
                        onClick={() => handleBatchRemoveDetails(envStatus, removableDetails)}>
                        批量移除 {removableDetails.length}
                      </Button>
                    </span>
                  </Tooltip>
                )}
                {hasContainerApp && (
                  <>
                    {image_uploading > 0 && <Tag color="processing" icon={<SyncOutlined spin />}>镜像上传中 ({image_uploading})</Tag>}
                    {image_success > 0 && <Tag color="success">镜像已上传 ({image_success})</Tag>}
                    {image_failed > 0 && <Tag color="error">镜像失败 ({image_failed})</Tag>}
                    <Tooltip title="容器应用将预先构建并上传镜像，发布时直接使用已上传的镜像">
                      <Button
                        size="small"
                        icon={<CloudUploadOutlined />}
                        disabled={!canPreUpload}
                        loading={uploadingEnv === env_id}
                        onClick={() => handlePreUploadImage(env_id, env_name, hasContainerApp)}
                      >
                        预传镜像
                      </Button>
                    </Tooltip>
                  </>
                )}
                <Button
                  type="primary"
                  size="small"
                  icon={<PlayCircleOutlined />}
                  disabled={!canPublish || store.isPublishing}
                  loading={store.isPublishing}
                  danger={is_prod}
                  onClick={() => handlePublish(env_id, env_name, is_prod)}
                >
                  {is_prod ? '发布生产' : '发布'}
                </Button>
              </Space>
            }
          >
            {warningDetails.length > 0 && (
              <Alert
                className={S.versionWarningBanner}
                type={hasDangerWarning ? 'error' : (onlyInfoWarning ? 'info' : 'warning')}
                showIcon
                message={
                  <span>
                    {warningDetails.length} 个应用需要关注
                    <span className={S.versionWarningBannerHint}>不影响发布，详情见“版本提示”列</span>
                  </span>
                }
              />
            )}
            <Table
              columns={detailColumns}
              dataSource={details || []}
              rowKey="id"
              rowClassName={detail => {
                const warning = detail.cross_iteration_warning;
                if (!warning || !warning.has_warning) return '';
                if (warning.level === 'danger') return S.versionDangerRow;
                if (warning.level === 'warning') return S.versionWarningRow;
                return S.versionInfoRow;
              }}
              pagination={false}
              size="small"
              scroll={{ x: 1080, y: 200 }}
            />
          </Card>
        );
      })}

      {publishStatus.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
          暂无发布数据
        </div>
      )}
      {imageLogRecord && (
        <ImageConsole
          record={imageLogRecord}
          onClose={() => setImageLogRecord(null)}
        />
      )}
    </Modal>
  );
}

export default observer(Publish);
