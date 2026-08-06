/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import {
  BuildOutlined,
  DownSquareOutlined,
  ExclamationCircleOutlined,
  OrderedListOutlined,
  ContainerOutlined,
  UpSquareOutlined,
  PlusOutlined
} from '@ant-design/icons';
import { Table, Modal, Radio, Tag, Divider, message, Tooltip } from 'antd';
import { http, hasPermission } from 'libs';
import { Action, TableCard, AuthButton } from "components";
import CloneConfirm from './CloneConfirm';
import store from './store';
import envStore from 'pages/config/environment/store';
import lds from 'lodash';
import tagStore from 'pages/config/tag/store';

function ComTable() {
  const [cleaning, setCleaning] = useState();

  function isFrontend(info) {
    return info.app_rel_tags?.some(tid => (
      tagStore.records.find(item => item.id === tid)?.key === 'front'
    ))
  }

  function handleClone(e, id) {
    e.stopPropagation();
    let deploy = null;
    Modal.confirm({
      icon: <ExclamationCircleOutlined/>,
      title: '选择克隆对象',
      content: <CloneConfirm onChange={v => deploy = v}/>,
      onOk: () => {
        if (!deploy) {
          message.error('请选择要克隆的应用及环境')
          return Promise.reject()
        }
        deploy.env_id = undefined;
        store.showExtForm(null, id, deploy, true)
      },
    })
  }

  function handleDelete(e, text) {
    e.stopPropagation();
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除应用【${text['name']}】?`,
      onOk: () => {
        return http.delete('/api/app/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords()
          })
      }
    })
  }

  function handleDeployDelete(text) {
    Modal.confirm({
      title: '删除确认',
      content: `删除发布配置将会影响基于该配置所创建发布申请的发布和回滚功能，确定要删除【${lds.get(envStore.idMap, `${text.env_id}.name`)}】的发布配置?`,
      onOk: () => {
        return http.delete('/api/app/deploy/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            store.loadDeploys(text.app_id)
          })
      }
    })
  }

  function handleClean(e, info) {
    e.stopPropagation();
    let target = 'node_modules';
    Modal.confirm({
      icon: <ExclamationCircleOutlined/>,
      title: '清理发布目录',
      width: 620,
      content: (
        <div>
          <p>请选择要清理的目录。清理后无法恢复，请确认当前没有需要保留的本地文件。</p>
          <Radio.Group
            defaultValue={target}
            onChange={event => target = event.target.value}>
            <Radio style={{display: 'block', marginBottom: 10}} value="node_modules">
              $SPUG_REPOS_DIR/$SPUG_DEPLOY_ID/node_modules（仅清理依赖）
            </Radio>
            <Radio style={{display: 'block'}} value="repo">
              $SPUG_REPOS_DIR/$SPUG_DEPLOY_ID（清理整个目录）
            </Radio>
          </Radio.Group>
        </div>
      ),
      okText: '确认清理',
      okButtonProps: {danger: true},
      onOk: () => {
        setCleaning(info.id);
        return http.post('/api/app/deploy/clean/', {
          deploy_id: info.id,
          target,
        }).then(response => {
          const label = target === 'repo' ? '发布目录' : 'node_modules 目录';
          message.success(response.removed ? `${label}清理成功` : `${label}不存在，无需清理`);
        }).finally(() => setCleaning(null))
      },
    })
  }

  function handleSort(e, info, sort) {
    e.stopPropagation();
    store.fetching = true;
    http.patch('/api/app/', {id: info.id, sort})
      .then(store.fetchRecords, () => store.fetching = false)
  }

  function handleExpand(expanded, row) {
    // 去掉row.isLoaded保证每次展开都会加载最新的，不然展开后会缓存一次，之后就不会再读取最新的
    if (expanded) {
      store.loadDeploys(row.id)
    }
  }

  function expandedRowRender(record) {
    return (
      <Table
        rowKey="id"
        loading={record['deploys'] === undefined}
        dataSource={record['deploys']}
        pagination={false}>
        <Table.Column width={80} title="模式" dataIndex="extend" render={value => (
            <div>
              {value === '1' ? <Tooltip title="常规发布"><OrderedListOutlined style={{fontSize: 20, color: '#1890ff'}}/></Tooltip> : null}
              {value === '2' ? <Tooltip title="自定义发布"><BuildOutlined style={{fontSize: 20, color: '#1890ff'}}/></Tooltip> : null}
              {value === '3' ? <Tooltip title="容器发布"><ContainerOutlined style={{fontSize: 20, color: '#1890ff'}}/></Tooltip> : null}
            </div>
        )}/>
        <Table.Column title="发布环境" render={(info) => (
          <div>
            {info.env_prod ? <Tag color="#f50">生产环境</Tag> : null}
            {lds.get(envStore.idMap, `${info.env_id}.name`)}
          </div>
        )}/>
        <Table.Column title="关联主机" dataIndex="host_ids" render={value => `${value.length} 台`}/>
        <Table.Column title="发布审核" dataIndex="is_audit"
                      render={value => value ? <Tag color="green">开启</Tag> : <Tag color="red">关闭</Tag>}/>
        {hasPermission('deploy.app.config|deploy.app.edit|deploy.app.clean') && (
          <Table.Column title="操作" render={info => (
            <Action>
              <Action.Button
                auth="deploy.app.config"
                onClick={e => store.showAutoDeploy(info)}>Webhook</Action.Button>
              {isFrontend(info) && (
                <Action.Button
                  auth="deploy.app.clean"
                  loading={cleaning === info.id}
                  onClick={e => handleClean(e, info)}>清理目录</Action.Button>
              )}
              {hasPermission('deploy.app.edit') ? (
                <Action.Button onClick={e => store.showExtForm(e, record.id, info)}>编辑</Action.Button>
              ) : hasPermission('deploy.app.config') ? (
                <Action.Button onClick={e => store.showExtForm(e, record.id, info, false, true)}>查看</Action.Button>
              ) : null}
              <Action.Button danger auth="deploy.app.edit" onClick={() => handleDeployDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </Table>
    )
  }

  return (
    <TableCard
      tKey="da"
      title="应用列表"
      rowKey="id"
      loading={store.isFetching}
      dataSource={store.dataSource}
      expandable={{expandedRowRender, expandRowByClick: true, onExpand: handleExpand}}
      onReload={store.fetchRecords}
      actions={[
        <AuthButton
          auth="deploy.app.add"
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
      <Table.Column width={80} title="排序" key="series" render={(info) => (
        <div>
          <UpSquareOutlined
            onClick={e => handleSort(e, info, 'up')}
            style={{cursor: 'pointer', color: '#1890ff'}}/>
          <Divider type="vertical"/>
          <DownSquareOutlined
            onClick={e => handleSort(e, info, 'down')}
            style={{cursor: 'pointer', color: '#1890ff'}}/>
        </div>
      )}/>
      <Table.Column title="应用名称" dataIndex="name"/>
      <Table.Column
          title="标签"
          render={(info) => (
            <div>
              {info.rel_tags?.length > 0 ? info.rel_tags.map(tid => (
                <Tag style={{ border: 'none' }} color="orange" key={`tag-${tid}`}>{tagStore.records.find(item => item.id === tid)?.name}</Tag>
              )) : ''}
            </div>
          )}
        />
      <Table.Column title="标识符" dataIndex="key"/>
      <Table.Column ellipsis title="描述信息" dataIndex="desc"/>
      {hasPermission('deploy.app.edit|deploy.app.del') && (
        <Table.Column width={260} title="操作" render={info => (
          <Action>
            <Action.Button auth="deploy.app.edit" onClick={e => store.showExtForm(e, info.id)}>新建发布</Action.Button>
            <Action.Button auth="deploy.app.edit" onClick={e => handleClone(e, info.id)}>克隆发布</Action.Button>
            <Action.Button auth="deploy.app.edit" onClick={e => store.showForm(e, info)}>编辑</Action.Button>
            <Action.Button danger auth="deploy.app.del" onClick={e => handleDelete(e, info)}>删除</Action.Button>
          </Action>
        )}/>
      )}
    </TableCard>
  )
}

export default observer(ComTable)
