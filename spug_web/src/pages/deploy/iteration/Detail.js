/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Descriptions, Table, Tag, Card, Space, Statistic, Row, Col, Progress, Tooltip } from 'antd';
import { 
  RocketOutlined, 
  ClockCircleOutlined, 
  UserOutlined, 
  CheckCircleOutlined, 
  AppstoreOutlined,
  CloudServerOutlined,
  SyncOutlined,
  CloseCircleOutlined,
  EyeOutlined
} from '@ant-design/icons';
import { AuthButton } from 'components';
import store from './store';

function Detail() {
  const record = store.record;

  // 自动刷新详情
  useEffect(() => {
    if (!store.detailVisible || !record.id) return;

    // 检查是否有正在进行的任务
    const hasRunningTasks = () => {
      return (record.details || []).some(detail => 
        detail.status === '1' || detail.image_status === '1'
      );
    };

    // 设置定时刷新
    const timer = setInterval(() => {
      if (store.detailVisible && record.id) {
        store.fetchRecordDetail(record.id);
        
        // 如果没有正在运行的任务，停止定时刷新
        if (!hasRunningTasks()) {
          clearInterval(timer);
        }
      }
    }, 3000); // 每3秒刷新一次

    return () => clearInterval(timer);
  }, [store.detailVisible, record.id, record.details]);

  // 按应用分组处理数据
  const groupedDetails = {};
  (record.details || []).forEach(detail => {
    if (!groupedDetails[detail.app_name]) {
      groupedDetails[detail.app_name] = {};
    }
    groupedDetails[detail.app_name][detail.env_name] = detail;
  });

  // 获取所有环境名称（按迭代中的环境顺序）
  const allEnvs = Array.from(new Set((record.details || []).map(d => d.env_name)));

  // 构建新的表格数据：按每个应用在详情中的最小 sequence 排序（来自数据库保存的顺序）
  const transformedDetails = Object.entries(groupedDetails)
    .map(([appName, envDetails]) => {
      // 计算该应用在所有环境中的最小 sequence
      const seqs = Object.values(envDetails).map(d => d && d.sequence ? d.sequence : Number.MAX_SAFE_INTEGER);
      const minSeq = seqs.length ? Math.min(...seqs) : Number.MAX_SAFE_INTEGER;
      return { appName, envDetails, minSeq };
    })
    .sort((a, b) => (a.minSeq || Number.MAX_SAFE_INTEGER) - (b.minSeq || Number.MAX_SAFE_INTEGER))
    .map((item, idx) => ({ key: item.appName, sequence: idx + 1, app_name: item.appName, ...item.envDetails }));

  // 动态生成列
  const detailColumns = [
    {
      title: '#',
      dataIndex: 'sequence',
      width: 60,
      render: (text) => (
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 28,
          height: 28,
          borderRadius: '50%',
          backgroundColor: '#1890ff',
          color: '#fff',
          fontWeight: 600,
          fontSize: 12
        }}>{text}</span>
      )
    },
    {
      title: '应用名称',
      dataIndex: 'app_name',
      width: 280,
      render: (text) => (
        <Space>
          <AppstoreOutlined style={{ color: '#1890ff' }} />
          <span style={{ fontWeight: 500 }}>{text}</span>
        </Space>
      )
    },
    ...allEnvs.map(envName => ({
      title: <Tag color="processing" style={{ margin: 0 }}>{envName}</Tag>,
      key: envName,
      align: 'center',
      render: (text, record) => {
        const detail = record[envName];
        if (!detail) {
          return <span style={{color: '#d9d9d9'}}>—</span>;
        }
        // 根据发布状态显示不同样式
        const detailStatusColors = {
          '0': 'processing',
          '1': 'warning',
          '2': 'success',
          '3': 'error',
        };
        const statusColor = detailStatusColors[detail.status] || 'default';
        
        // 镜像状态图标
        const getImageStatusIcon = () => {
          if (!detail.is_container) return null;
          switch (detail.image_status) {
            case '1':
              return (
                <Tooltip title="镜像上传中">
                  <Tag color="processing" icon={<SyncOutlined spin />} style={{ fontSize: 10, padding: '0 4px' }}>
                    镜像上传中
                  </Tag>
                </Tooltip>
              );
            case '2':
              return (
                <Tooltip title="镜像已上传">
                  <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: 10, padding: '0 4px' }}>
                    镜像就绪
                  </Tag>
                </Tooltip>
              );
            case '3':
              return (
                <Tooltip title="镜像上传失败">
                  <Tag color="error" icon={<CloseCircleOutlined />} style={{ fontSize: 10, padding: '0 4px' }}>
                    镜像失败
                  </Tag>
                </Tooltip>
              );
            default:
              return detail.is_container ? (
                <Tooltip title="容器应用（未预传镜像）">
                  <CloudServerOutlined style={{ color: '#1890ff', fontSize: 12 }} />
                </Tooltip>
              ) : null;
          }
        };
        
        return (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <Tag color={statusColor} style={{ fontFamily: 'monospace' }}>{detail.version}</Tag>
            {detail.status && detail.status !== '0' && (
              <Tag color={statusColor} style={{ fontSize: 10 }}>{detail.status_alias}</Tag>
            )}
            {getImageStatusIcon()}
            {detail.request_id ? (
              <AuthButton
                auth="deploy.request.view"
                type="link"
                size="small"
                icon={<EyeOutlined />}
                onClick={() => store.showRequestDetail(detail.request_id)}>
                查看申请
              </AuthButton>
            ) : null}
          </div>
        );
      }
    }))
  ];

  const getStatusColor = (status) => {
    const colors = {
      '0': 'processing',
      '1': 'warning',
      '2': 'success',
      '-1': 'default',
      '-3': 'error'
    };
    return colors[status] || 'default';
  };

  const statusMap = {
    '0': '待发布',
    '1': '发布中',
    '2': '发布成功',
    '-1': '部分失败',
    '-3': '发布失败'
  };

  // 计算统计数据
  const totalApps = Object.keys(groupedDetails).length;
  const totalEnvs = allEnvs.length;
  const totalItems = record.details ? record.details.length : 0;
  // 已发布数量：从后端获取，或者计算 details 中 status='3' 的数量
  const publishedCount = record.published_count || 0;
  const progressPercent = totalItems > 0 ? Math.round((publishedCount / totalItems) * 100) : 0;

  return (
    <Modal
      title={
        <Space>
          <RocketOutlined style={{ color: '#1890ff' }} />
          <span>迭代详情</span>
        </Space>
      }
      visible={store.detailVisible}
      onCancel={() => store.closeDetail()}
      footer={null}
      width={1000}
      bodyStyle={{ padding: '16px 24px' }}
    >
      {/* 头部统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Card size="small" bordered={false} style={{ background: '#f6ffed', borderRadius: 8 }}>
            <Statistic
              title={<span style={{ color: '#52c41a' }}>迭代名称</span>}
              value={record.name || '-'}
              valueStyle={{ fontSize: 16, color: '#52c41a' }}
              prefix={<RocketOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" bordered={false} style={{ background: '#e6f7ff', borderRadius: 8 }}>
            <Statistic
              title={<span style={{ color: '#1890ff' }}>发布环境</span>}
              value={totalEnvs}
              suffix="个"
              valueStyle={{ fontSize: 16, color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" bordered={false} style={{ background: '#fff7e6', borderRadius: 8 }}>
            <Statistic
              title={<span style={{ color: '#fa8c16' }}>应用数量</span>}
              value={totalApps}
              suffix="个"
              valueStyle={{ fontSize: 16, color: '#fa8c16' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" bordered={false} style={{ background: '#f9f0ff', borderRadius: 8 }}>
            <div style={{ marginBottom: 8 }}>
              <span style={{ color: '#722ed1', fontSize: 12 }}>发布进度</span>
            </div>
            <Progress 
              percent={progressPercent} 
              size="small"
              status={progressPercent === 100 ? 'success' : 'active'}
              format={() => `${publishedCount}/${totalItems}`}
              strokeColor="#722ed1"
            />
          </Card>
        </Col>
      </Row>

      {/* 基本信息 */}
      <Card 
        title={<span style={{ fontSize: 14 }}>基本信息</span>} 
        size="small" 
        style={{ marginBottom: 16, borderRadius: 8 }}
        headStyle={{ background: '#fafafa', borderRadius: '8px 8px 0 0' }}
      >
        <Descriptions size="small" column={3}>
          <Descriptions.Item label={<Space><UserOutlined />创建人</Space>}>
            {record.created_by_user || '-'}
          </Descriptions.Item>
          <Descriptions.Item label={<Space><ClockCircleOutlined />创建时间</Space>}>
            {record.created_at || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={getStatusColor(record.status)}>{statusMap[record.status] || '-'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="发布环境" span={3}>
            <Space size={4} wrap>
              {record.env_list && Array.isArray(record.env_list) && record.env_list.length > 0 ? 
                record.env_list.map((env, idx) => (
                  <span key={idx}>
                    {env.prod ? <Tag color="#f50" style={{ marginRight: 2 }}>{env.name}</Tag> : <Tag color="default" style={{ marginRight: 2 }}>{env.name}</Tag>}
                  </span>
                )) : 
                (record.env_name ? record.env_name.split(',').map((env, idx) => (
                  <Tag key={idx} color="default">{env.trim()}</Tag>
                )) : '-')
              }
            </Space>
          </Descriptions.Item>
          {record.desc && (
            <Descriptions.Item label="描述" span={3}>
              <span style={{ color: '#666' }}>{record.desc}</span>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {/* 发布项详情 */}
      <Card 
        title={
          <Space>
            <span style={{ fontSize: 14 }}>发布项详情</span>
            <Tag color="blue">{totalItems} 项</Tag>
          </Space>
        }
        size="small"
        style={{ borderRadius: 8 }}
        headStyle={{ background: '#fafafa', borderRadius: '8px 8px 0 0' }}
      >
        <Table
          columns={detailColumns}
          dataSource={transformedDetails}
          rowKey="key"
          pagination={false}
          size="small"
          scroll={{ x: 'max-content' }}
          style={{ marginTop: 8 }}
        />
      </Card>
    </Modal>
  )
}

export default observer(Detail)
