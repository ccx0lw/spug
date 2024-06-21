/**
 * Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
 * Copyright: (c) <fcjava@163.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, Tag, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { Action, TableCard, AuthButton } from 'components';
import { http, hasPermission } from 'libs';
import store from './store';
import tagStore from 'pages/config/tag/store';

function ComTable() {
  const [loading, setLoading] = useState();
  const tags = tagStore.records;

  function handleRebuild(info) {
    if (info.status === '5') {
      Modal.confirm({
        title: '重新构建提示',
        content: `当前选择版本 ${info.version} 已完成构建，再次构建将覆盖已有的数据，要再次重新构建吗？`,
        onOk: () => _rebuild(info)
      })
    } else if (info.status === '1') {
      return message.error('已在构建中，请点击日志查看详情')
    } else {
      _rebuild(info)
    }
  }

  function _rebuild(info) {
    setLoading(info.id);
    http.patch('/api/docker_image/', {id: info.id, action: 'rebuild'})
      .then(() => store.showConsole(info))
      .finally(() => setLoading(null))
  }

  function expandedRowRender(record) {
    return (
      <Table rowKey="id" dataSource={record.child} pagination={false}>
        <Table.Column title="版本" render={info => (
          <div style={{color: '#1890ff', cursor: 'pointer'}} onClick={() => store.showDetail(info)}>{info.version}</div>
        )}/>
        <Table.Column title="环境" dataIndex="env_name"/>
        <Table.Column title="构建时间" dataIndex="created_at"/>
        <Table.Column title="备注" dataIndex="remarks"/>
        <Table.Column title="状态" render={info => <Tag color={statusColorMap[info.status]}>{info.status_alias}</Tag>}/>
        {hasPermission('deploy.docker_image.detail|deploy.docker_image.build|deploy.docker_image.log') && (
          <Table.Column width={180} title="操作" render={info => (
            <Action>
              <Action.Button
                auth="deploy.docker_image.build"
                loading={loading === info.id}
                disabled={info.remarks === 'SPUG AUTO MAKE' || info.status === '5'}
                onClick={() => handleRebuild(info)}>构建</Action.Button>
              <Action.Button auth="deploy.docker_image.build" onClick={() => store.showConsole(info)}>日志</Action.Button>
            </Action>
          )}/>
        )}
      </Table>
    )
  }

  const statusColorMap = {'0': 'cyan', '1': 'blue', '2': 'red', '5': 'green'};
  return (
    <TableCard
      tKey="dre"
      rowKey="id"
      title="构建版本列表"
      loading={store.isFetching}
      dataSource={store.dataSource}
      onReload={store.fetchRecords}
      actions={[
        <AuthButton
          auth="deploy.docker_image.add"
          type="primary"
          icon={<PlusOutlined/>}
          onClick={store.showForm}>新建</AuthButton>
      ]}
      expandable={{expandedRowRender, expandRowByClick: true}}
      pagination={{
        showSizeChanger: true,
        showLessItems: true,
        showTotal: total => `共 ${total} 条`,
        pageSizeOptions: ['10', '20', '50', '100']
      }}>
      <Table.Column title="应用" dataIndex="app_name"/>
      <Table.Column title="标签" render={(info) => (
        <div>
          {info.app_rel_tags?.length > 0 ? info.app_rel_tags.map(tid => (
            <Tag style={{ border: 'none' }} color="orange" key={`tag-${tid}`}>{tags.find(item => item.id === tid)?.name}</Tag>
          )) : null}
        </div>
      )}
      />
      <Table.Column title="最新版本" render={info => `${info.version}（${info.env_name}）`}/>
      <Table.Column title="构建时间" dataIndex="created_at"/>
      <Table.Column title="构建人" dataIndex="created_by_user"/>
      <Table.Column width={100} title="状态"
                    render={info => <Tag color={statusColorMap[info.status]}>{info.status_alias}</Tag>}/>

    </TableCard>
  )
}

export default observer(ComTable)
