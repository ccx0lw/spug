/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { Action, TableCard, AuthButton } from 'components';
import { http, hasPermission } from 'libs';
import store from './store';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords()
  }

  handleDelete = (text) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${text['name']}】?`,
      onOk: () => {
        return http.delete('/api/config/tag/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords()
          })
      }
    })
  };

  render() {
    let data = store.records;
    if (store.f_name) {
      data = data.filter(item => item['name'].toLowerCase().includes(store.f_name.toLowerCase()))
    }
    return (
      <TableCard
        tKey="ca"
        rowKey="id"
        title="标签列表"
        loading={store.isFetching}
        dataSource={data}
        onReload={store.fetchRecords}
        actions={[
          <AuthButton
            auth="config.app.add"
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showForm()}>新建</AuthButton>
        ]}
        pagination={{
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100']
        }}>
        <Table.Column title="标签名称" dataIndex="name"/>
        <Table.Column title="标识符" dataIndex="key"/>
        <Table.Column ellipsis title="描述信息" dataIndex="desc"/>
        {hasPermission('config.tag.edit|config.tag.del|config.tag.view_config') && (
          <Table.Column width={210} title="操作" render={info => (
            <Action>
              <Action.Button auth="config.tag.edit" onClick={() => store.showForm(info)}>编辑</Action.Button>
              <Action.Button danger auth="config.tag.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    )
  }
}

export default ComTable
