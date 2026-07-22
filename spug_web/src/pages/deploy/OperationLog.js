/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { Modal, Table, message } from 'antd';
import { http } from 'libs';

function OperationLog({ visible, targetType, targetId, targetName, onCancel }) {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!visible || !targetType || !targetId) return;
    setRecords([]);
    setLoading(true);
    http.get('/api/deploy/operation-log/', {
      params: {
        target_type: targetType,
        target_id: targetId,
      },
    }).then(setRecords)
      .catch(error => message.error(error.message || '读取操作日志失败'))
      .finally(() => setLoading(false));
  }, [visible, targetType, targetId]);

  return (
    <Modal
      title={`操作日志 - ${targetName || ''}`}
      visible={visible}
      onCancel={onCancel}
      footer={null}
      width={680}
      destroyOnClose
    >
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={records}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: '暂无操作日志' }}
        columns={[
          {
            title: '操作人',
            dataIndex: 'operator_name',
            width: 140,
          },
          {
            title: '操作',
            dataIndex: 'action',
          },
          {
            title: '操作时间',
            dataIndex: 'created_at',
            width: 180,
          },
        ]}
      />
    </Modal>
  );
}

export default OperationLog;
