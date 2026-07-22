/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {Descriptions, Tag} from 'antd';


export default function RequestSummary({request}) {
  const statusColors = {
    '-3': 'error',
    '-1': 'error',
    '0': 'processing',
    '1': 'warning',
    '2': 'warning',
    '3': 'success',
  };

  return (
    <Descriptions bordered size="small" column={3} style={{marginBottom: 20}}>
      <Descriptions.Item label="应用">{request.app_name || '-'}</Descriptions.Item>
      <Descriptions.Item label="发布环境">
        {request.env_prod ? <Tag color="error">生产环境</Tag> : null}
        {request.env_name || '-'}
      </Descriptions.Item>
      <Descriptions.Item label="状态">
        <Tag color={statusColors[request.status] || 'default'}>
          {request.status_alias || '-'}
        </Tag>
      </Descriptions.Item>
      <Descriptions.Item label="发布类型">{request.type_alias || '-'}</Descriptions.Item>
      <Descriptions.Item label="版本">{request.version || '-'}</Descriptions.Item>
      <Descriptions.Item label="申请人">{request.created_by_user || '-'}</Descriptions.Item>
      <Descriptions.Item label="申请时间">{request.created_at || '-'}</Descriptions.Item>
      <Descriptions.Item label="发布人">{request.do_by_user || '-'}</Descriptions.Item>
      <Descriptions.Item label="发布时间">{request.do_at || '-'}</Descriptions.Item>
      {request.desc ? (
        <Descriptions.Item label="备注" span={3}>{request.desc}</Descriptions.Item>
      ) : null}
    </Descriptions>
  )
}
