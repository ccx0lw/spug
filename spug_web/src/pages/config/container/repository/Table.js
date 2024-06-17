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
import envStore from 'pages/config/environment/store';
import lds from 'lodash';

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
        return http.delete('/api/config/container/repository/', {params: {id: text.id}})
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
        title="容器仓库列表"
        loading={store.isFetching}
        dataSource={data}
        onReload={store.fetchRecords}
        actions={[
          <AuthButton
            auth="config.container.repository.add"
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
        <Table.Column title="环境" render={info => (
          <span>
            {lds.get(envStore.idMap, `${info.env_id}.name`)}
          </span>
        )}/>
        <Table.Column title="仓库地址" dataIndex="repository"/>
        <Table.Column title="镜像前缀" dataIndex="repository_name_prefix"/>
        <Table.Column ellipsis title="描述信息" dataIndex="desc"/>
        {hasPermission('config.container.repository.edit|config.container.repository.del|config.container.repository.view_config') && (
          <Table.Column width={210} title="操作" render={info => (
            <Action>
              <Action.Button auth="config.container.repository.edit" onClick={() => store.showForm(info)}>编辑</Action.Button>
              <Action.Button danger auth="config.container.repository.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    )
  }
}

export default ComTable
