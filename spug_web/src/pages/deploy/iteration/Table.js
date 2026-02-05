/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Space, Popconfirm, Tooltip, Progress } from 'antd';
import { RocketOutlined, CloudServerOutlined, SyncOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { AuthButton, Action } from 'components';
import store from './store';
import S from './index.module.less';

function ComTable() {
  const getStatusColor = (status) => {
    const colors = {
      '0': 'blue',
      '1': 'orange',
      '2': 'green',
      '-1': 'red',
      '-3': 'magenta'
    };
    return colors[status] || 'default';
  };

  const columns = [
    {
      title: '迭代名称',
      className: S.min80,
      dataIndex: 'name',
      render: (text, record) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <RocketOutlined style={{ color: '#1890ff' }} />
          <span style={{ fontWeight: 500 }}>{text}</span>
        </div>
      )
    },
    {
      title: '发布环境',
      className: S.min80,
      dataIndex: 'env_list',
      render: (envList, record) => {
        // 优先使用 env_list（包含 prod 信息），否则回退到 env_name
        if (envList && Array.isArray(envList) && envList.length > 0) {
          return (
            <Space size={4} wrap>
              {envList.map((env, idx) => (
                <span key={idx}>
                  {env.prod ? <Tag color="#f50" style={{ margin: 0, marginRight: 2 }}>{env.name}</Tag> : <Tag color="default" style={{ margin: 0 }}>{env.name}</Tag>}
                </span>
              ))}
            </Space>
          );
        }
        // 回退逻辑
        const text = record.env_name;
        if (!text) return '-';
        const envs = text.split(',').map(s => s.trim()).filter(Boolean);
        return (
          <Space size={4} wrap>
            {envs.map((env, idx) => (
              <Tag key={idx} color="blue" style={{ margin: 0 }}>{env}</Tag>
            ))}
          </Space>
        );
      }
    },
    {
      title: '发布进度',
      className: S.min80,
      dataIndex: 'details',
      width: 140,
      render: (details, record) => {
        // 已发布数量：从后端获取
        const publishedCount = record.published_count || 0;
        // 发布总数：环境+应用的组合数（即 details 数组长度）
        const totalCount = details ? details.length : 0;
        const percent = totalCount > 0 ? Math.round((publishedCount / totalCount) * 100) : 0;
        return (
          <Tooltip title={`已发布 ${publishedCount} / 共 ${totalCount} 项`}>
            <div style={{ minWidth: 100 }}>
              <Progress 
                percent={percent} 
                size="small" 
                status={percent === 100 ? 'success' : 'active'}
                format={() => `${publishedCount}/${totalCount}`}
              />
            </div>
          </Tooltip>
        );
      }
    },
    {
      title: '创建人',
      dataIndex: 'created_by_user',
      width: 100,
    },
    {
      title: '创建时间',
      className: S.min80,
      dataIndex: 'created_at',
      render: (text) => (
        <Tooltip title={text}>
          <span style={{ color: '#666' }}>{text}</span>
        </Tooltip>
      )
    },
    {
      title: '状态',
      className: S.min80,
      dataIndex: 'status_alias',
      fixed: 'right',
      render: (text, record) => (
        <Tag color={getStatusColor(record.status)} className={S.statusTag}>{text}</Tag>
      )
    },
    {
      title: '操作',
      className: S.min80,
      fixed: 'right',
      render: (text, record) => {
        // 只有待发布状态才能编辑和删除
        const canEdit = record.status === '0';
        const canDelete = record.status === '0';
        
        return (
          <Action>
            <Action.Button
              auth="deploy.iteration.do"
              onClick={() => store.showPublish(record)}>发布</Action.Button>
            <Action.Button
              auth="deploy.iteration.view"
              onClick={() => store.showDetail(record)}>查看</Action.Button>
            {canEdit && (
              <Action.Button
                auth="deploy.iteration.edit"
                onClick={() => {
                  store.record = record;
                  store.formVisible = true;
                }}>编辑</Action.Button>
            )}
            {canDelete && (
              <Popconfirm
                title="确定要删除该迭代吗?"
                onConfirm={() => store.deleteRecord(record.id)}
                okText="确定"
                cancelText="取消"
              >
                <Action.Button auth="deploy.iteration.del" danger>删除</Action.Button>
              </Popconfirm>
            )}
          </Action>
        );
      }
    }
  ];

  // 展开行的内容
  const expandedRowRender = (record) => {
    // 镜像状态显示
    const getImageStatusTag = (imageStatus, isContainer) => {
      if (!isContainer) return <span style={{ color: '#999' }}>-</span>;
      switch (imageStatus) {
        case '0':
          return <Tag color="default"><CloudServerOutlined /> 未上传</Tag>;
        case '1':
          return <Tag color="processing" icon={<SyncOutlined spin />}>上传中</Tag>;
        case '2':
          return <Tag color="success" icon={<CheckCircleOutlined />}>已上传</Tag>;
        case '3':
          return <Tag color="error" icon={<CloseCircleOutlined />}>上传失败</Tag>;
        default:
          return <span style={{ color: '#999' }}>-</span>;
      }
    };

    const detailColumns = [
      {
        title: '#',
        dataIndex: 'sequence',
        width: 60,
        render: (text) => <span style={{ color: '#999' }}>{text}</span>
      },
      {
        title: '应用名称',
        dataIndex: 'app_name',
        render: (text) => <span style={{ fontWeight: 500 }}>{text}</span>
      },
      {
        title: '发布环境',
        dataIndex: 'env_name',
        render: (text, item) => (
          <Space size={2}>
            {item.env_prod ? <Tag color="#f50">{text}</Tag> : <Tag color="default">{text}</Tag>}
          </Space>
        )
      },
      {
        title: '版本',
        dataIndex: 'version',
        render: (text) => text ? <Tag color="success">{text}</Tag> : <span style={{ color: '#ccc' }}>-</span>
      },
      {
        title: '镜像状态',
        dataIndex: 'image_status',
        width: 120,
        render: (imageStatus, item) => getImageStatusTag(imageStatus, item.is_container)
      },
      {
        title: '发布状态',
        dataIndex: 'status',
        width: 100,
        render: (status, item) => {
          const statusColors = {
            '0': 'processing',
            '1': 'warning',
            '2': 'success',
            '3': 'error',
          };
          return <Tag color={statusColors[status] || 'default'}>{item.status_alias || '待发布'}</Tag>;
        }
      }
    ];

    const data = record.details || [];
    return (
      <div className={S.expandedTable}>
        {record.desc && (
          <div style={{ 
            padding: '8px 12px', 
            marginBottom: 12, 
            backgroundColor: '#f6f6f6', 
            borderRadius: 4,
            color: '#666',
            fontSize: 13
          }}>
            <span style={{ fontWeight: 500, marginRight: 8 }}>描述：</span>
            {record.desc}
          </div>
        )}
        <Table
          columns={detailColumns}
          dataSource={data}
          rowKey={(item) => `${item.app_id}_${item.env_id}_${item.id}`}
          pagination={false}
          size="small"
          showHeader={true}
        />
      </div>
    );
  };

  return (
    <div className={S.tableCard}>
      <Table 
        columns={columns}
        dataSource={store.dataSource}
        rowKey="id"
        pagination={{
          pageSize: 100,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: total => `共 ${total} 条`,
          // pageSizeOptions: ['10', '20', '50', '100']
        }}
        loading={store.isFetching}
        scroll={{ x: 900 }}
        expandable={{
          expandedRowRender,
          expandRowByClick: true,
          rowExpandable: (record) => record.details && record.details.length > 0
        }}
      />
    </div>
  )
}

export default observer(ComTable)
