/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { PlusOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import { Select, DatePicker, Input, Button, Space, Card } from 'antd';
import { SearchForm, AuthDiv, AuthButton, Breadcrumb } from 'components';
import { includes } from 'libs';
import envStore from 'pages/config/environment/store';
import appStore from 'pages/config/app/store';
import store from './store';
import moment from 'moment';
import ComTable from './Table';
import Form from './Form';
import Detail from './Detail';
import Publish from './Publish';
import RequestDetail from 'pages/deploy/request/Detail';

function Index() {
  useEffect(() => {
    store.fetchRecords()
    if (envStore.records.length === 0) envStore.fetchRecords()
    if (appStore.records.length === 0) appStore.fetchRecords()
  }, [])

  return (
    <AuthDiv auth="deploy.iteration.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>应用发布</Breadcrumb.Item>
        <Breadcrumb.Item>迭代发布</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={8} title="迭代名称">
          <Input 
            allowClear
            placeholder="请输入迭代名称"
            value={store.f_name || ''}
            onChange={e => store.f_name = e.target.value || undefined}
            prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
          />
        </SearchForm.Item>
        <SearchForm.Item span={8} title="发布环境">
          <Select
            allowClear
            showSearch
            value={store.f_env_id}
            filterOption={(i, o) => includes(o.children, i)}
            onChange={v => store.f_env_id = v}
            placeholder="请选择">
            {envStore.records.map(item => (
              <Select.Option key={item.id} value={item.id}>{item.name}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={8} title="状态">
          <Select
            allowClear
            value={store.f_status}
            onChange={v => store.f_status = v}
            placeholder="请选择">
            <Select.Option value="0">待发布</Select.Option>
            <Select.Option value="1">发布中</Select.Option>
            <Select.Option value="2">发布成功</Select.Option>
            <Select.Option value="-1">部分失败</Select.Option>
            <Select.Option value="-3">发布失败</Select.Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={8} title="创建时间">
          <DatePicker.RangePicker
            value={store.f_s_date ? [moment(store.f_s_date), moment(store.f_e_date)] : undefined}
            onChange={store.updateDate}
            style={{ width: '100%' }}
          />
        </SearchForm.Item>
        <SearchForm.Item span={16} style={{textAlign: 'right'}}>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => store.fetchRecords()}>刷新</Button>
            <AuthButton
              auth="deploy.iteration.add"
              type="primary"
              icon={<PlusOutlined/>}
              onClick={() => store.formVisible = true}>新建</AuthButton>
          </Space>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <Form/>}
      {store.detailVisible && <Detail/>}
      {store.publishVisible && <Publish/>}
      {store.requestDetailId && (
        <RequestDetail
          requestId={store.requestDetailId}
          onClose={store.closeRequestDetail}/>
      )}
    </AuthDiv>
  )
}

export default observer(Index)
