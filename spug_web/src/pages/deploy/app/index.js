/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Input, Select } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import Ext1Form from './Ext1Form';
import Ext2Form from './Ext2Form';
import Ext3Form from './Ext3Form';
import AddSelect from './AddSelect';
import AutoDeploy from './AutoDeploy';
import store from './store';
import envStore from 'pages/config/environment/store';
import tagStore from 'pages/config/tag/store';

export default observer(function () {
  useEffect(() => {
    store.fetchRecords();
    envStore.fetchRecords();
    tagStore.fetchRecords();
  }, [])

  const tags = tagStore.records || []

  return (
    <AuthDiv auth="deploy.app.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>应用发布</Breadcrumb.Item>
        <Breadcrumb.Item>应用管理</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={7} title="标签">
          <Select allowClear value={store.f_tag} onChange={e => store.f_tag = e} placeholder="请选择">
            { tags.map(item => (
              <Select.Option key={item.id} value={item.id}>
                <span>{item.name}</span>
              </Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={7} title="应用名称">
          <Input allowClear value={store.f_name} onChange={e => store.f_name = e.target.value} placeholder="请输入"/>
        </SearchForm.Item>
        <SearchForm.Item span={7} title="描述信息">
          <Input allowClear value={store.f_desc} onChange={e => store.f_desc = e.target.value} placeholder="请输入"/>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
      {store.addVisible && <AddSelect/>}
      {store.ext1Visible && <Ext1Form/>}
      {store.ext2Visible && <Ext2Form/>}
      {store.ext3Visible && <Ext3Form/>}
      {store.autoVisible && <AutoDeploy/>}
    </AuthDiv>
  );
})
