/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect, useRef } from 'react';
import { observer } from 'mobx-react';
import { Form, Modal, Input, Select, Button, Table, Space, Spin, message, Divider, Tag, Checkbox, Tabs, Card, Row, Col, Badge, Tooltip, Alert } from 'antd';
import { PlusOutlined, DeleteOutlined, DragOutlined, SearchOutlined, AppstoreOutlined, RocketOutlined, EnvironmentOutlined, ArrowUpOutlined, ArrowDownOutlined, CloseOutlined, CheckCircleOutlined } from '@ant-design/icons';
import store from './store';
import envStore from 'pages/config/environment/store';
import deployStore from 'pages/deploy/app/store';
import tagStore from 'pages/config/tag/store';
import { includes, http } from 'libs';

function FormComponent() {
  const [form] = Form.useForm();
  const nameInputRef = useRef(null);
  const [details, setDetails] = useState(store.record?.details || []);
  const [selectedEnvIds, setSelectedEnvIds] = useState(store.record?.env_ids || []);
  const [selectedAppId, setSelectedAppId] = useState(undefined);
  const [selectedVersion, setSelectedVersion] = useState(undefined);
  const [availableVersions, setAvailableVersions] = useState([]);
  const [versionLoading, setVersionLoading] = useState(false);
  const [tagList, setTagList] = useState([]);
  const [selectedTag, setSelectedTag] = useState('ALL');
  const [selectedAppsMap, setSelectedAppsMap] = useState({});
  const [searchAppName, setSearchAppName] = useState('');
  const [showMode, setShowMode] = useState('all');
  const [apps, setApps] = useState([]);
  const [initLoading, setInitLoading] = useState(true);

  const isEdit = !!store.record?.id;

  // 监听弹框显示，每次打开都重新加载数据
  useEffect(() => {
    if (!store.formVisible) return;
    
    setInitLoading(true);
    const loadData = async () => {
      try {
        // 初始化环境存储
        if (!envStore.records || envStore.records.length === 0) {
          const result = envStore.fetchRecords?.();
          if (result instanceof Promise) await result;
          else await new Promise(resolve => setTimeout(resolve, 100));
        }

        // 加载应用列表（等待完成）
        const fetchResult = deployStore.fetchRecords();
        if (fetchResult instanceof Promise) {
          await fetchResult;
        } else {
          await new Promise(resolve => setTimeout(resolve, 200));
        }

        // 确保有应用数据，如果没有则重新加载
        let appsToLoad = Array.isArray(deployStore.records) 
          ? deployStore.records 
          : Object.values(deployStore.records || {});
        
        if (appsToLoad.length === 0) {
          console.warn('应用列表为空，重新加载');
          const retryResult = deployStore.fetchRecords();
          if (retryResult instanceof Promise) {
            await retryResult;
          }
          appsToLoad = Array.isArray(deployStore.records) 
            ? deployStore.records 
            : Object.values(deployStore.records || {});
        }
          
        const appPromises = appsToLoad.map(app => {
          if (!app.isLoaded) {
            return deployStore.loadDeploys(app.id);
          }
          return Promise.resolve();
        });
        await Promise.all(appPromises);

        const appList = appsToLoad.map(app => ({
          id: app.id,
          name: app.name,
          key: app.key,
          rel_tags: app.rel_tags || []
        }));
        setApps(appList);

        // 加载标签列表
        const tagResult = tagStore.fetchRecords && tagStore.fetchRecords();
        if (tagResult instanceof Promise) await tagResult;
        setTagList(tagStore.records || []);

        // 编辑模式下恢复状态
        if (isEdit && store.record?.env_ids) {
          setSelectedEnvIds(store.record.env_ids);

          // 初始化 details 与 selectedAppsMap，保持已有的 sequence -> selectedOrder
          const existingDetails = Array.isArray(store.record.details) ? store.record.details.map(d => ({ ...d, key: d.id ? `edit_${d.id}` : `edit_${Date.now()}_${d.env_id}` })) : [];
          setDetails(existingDetails);

          // 构建 selectedAppsMap：以每个应用的最小 sequence 作为其 selectedOrder，保留 version
          const tempMap = {};
          existingDetails.forEach(d => {
            if (!tempMap[d.app_id]) {
              tempMap[d.app_id] = {
                selected: true,
                version: d.version || '',
                // 若有来自后端的版本，预先填充 availableVersions，避免编辑时显示加载中
                availableVersions: d.version ? [{ name: d.version, author: d.created_by_user || '', date: d.created_at || '' }] : [],
                loading: false,
                selectedOrder: d.sequence || Number.MAX_SAFE_INTEGER
              };
            } else {
              tempMap[d.app_id].selectedOrder = Math.min(tempMap[d.app_id].selectedOrder || Number.MAX_SAFE_INTEGER, d.sequence || Number.MAX_SAFE_INTEGER);
              if (!tempMap[d.app_id].version && d.version) tempMap[d.app_id].version = d.version;
              if ((!Array.isArray(tempMap[d.app_id].availableVersions) || tempMap[d.app_id].availableVersions.length === 0) && d.version) {
                tempMap[d.app_id].availableVersions = [{ name: d.version, author: d.created_by_user || '', date: d.created_at || '' }];
              }
            }
          });
          // 规范 selectedOrder 从1开始连续
          const sortedApps = Object.keys(tempMap).sort((a, b) => (tempMap[a].selectedOrder || Number.MAX_SAFE_INTEGER) - (tempMap[b].selectedOrder || Number.MAX_SAFE_INTEGER));
          sortedApps.forEach((aid, i) => { tempMap[aid].selectedOrder = i + 1; });
          setSelectedAppsMap(tempMap);
        } else if (!isEdit) {
          // 新建模式下默认选择所有环境
          setSelectedEnvIds(envStore.records.map(e => e.id));
        }
      } catch (error) {
        console.error('加载数据失败:', error);
        message.error('加载数据失败');
      } finally {
        setInitLoading(false);
        // 确保在弹窗完全显示后将焦点移动到第一个输入，避免背景元素在被 aria-hidden 时仍保有焦点
        setTimeout(() => {
          try {
            const active = document.activeElement;
            if (active && active !== document.body && active !== nameInputRef.current) {
              try { active.blur(); } catch (e) { /* ignore */ }
            }
            nameInputRef.current && nameInputRef.current.focus && nameInputRef.current.focus();
          } catch (e) {
            // ignore
          }
        }, 50);
      }
    };
    loadData();
  }, [store.formVisible]);

  // 当环境选择改变时，重新加载版本
  useEffect(() => {
    if (selectedAppId) {
      handleAppChange(selectedAppId);
    }
  }, [selectedEnvIds]);

  // 当选择应用时，加载第一个环境的版本
  const handleAppChange = async (appId) => {
    setSelectedAppId(appId);
    setSelectedVersion(undefined);
    setAvailableVersions([]);
    
    if (!appId || !selectedEnvIds || selectedEnvIds.length === 0) return;

    // 获取第一个环境
    const firstEnvId = selectedEnvIds[0];
    
    setVersionLoading(true);
    
    try {
      // 从 deployStore 中查找该应用在该环境的部署配置
      let deployId = null;
      
      // deployStore.records 可能是数组或对象
      const appsArray = Array.isArray(deployStore.records) 
        ? deployStore.records 
        : Object.values(deployStore.records || {});
      
      for (const app of appsArray) {
        if (app.deploys && Array.isArray(app.deploys)) {
          const deploy = app.deploys.find(d => d.env_id === firstEnvId && d.app_id === appId);
          if (deploy) {
            deployId = deploy.id;
            break;
          }
        }
      }

      if (!deployId) {
        message.warning('该应用在选定环境中没有部署配置');
        setVersionLoading(false);
        return;
      }

      // 获取版本列表
      const response = await http.get(`/api/app/deploy/${deployId}/versions/`);
      
      // 响应结构是 { data: {...}, error: '' }
      if (response.error) {
        message.error(response.error);
        setVersionLoading(false);
        return;
      }
      
      // 从 response.data 中获取 tags
      const responseData = response.data || response;
      let tags = responseData.tags || {};
      
      // tags 是一个对象，key 是标签名（如 v1.0.3），value 是提交信息
      // 构建版本列表，包含完整的信息
      const versionList = Object.entries(tags).map(([name, info]) => ({
        name,
        id: info.id,
        author: info.author,
        date: info.date,
        message: info.message
      }));
      
      if (versionList.length > 0) {
        setAvailableVersions(versionList);
        // 自动选择最新版本的名称（第一个）
        setSelectedVersion(versionList[0].name);
      } else {
        message.warning('未找到可用版本');
      }
    } catch (error) {
      console.error('获取版本失败:', error);
      message.error(error.message || '获取版本失败');
    } finally {
      setVersionLoading(false);
    }
  };

  const removeEnv = (envId) => {
    const newEnvIds = selectedEnvIds.filter(id => id !== envId);
    setSelectedEnvIds(newEnvIds);
    // 同时删除该环境的所有应用
    setDetails(details.filter(d => d.env_id !== envId));
  };

  const moveEnv = (fromIndex, toIndex) => {
    const newEnvIds = [...selectedEnvIds];
    const [env] = newEnvIds.splice(fromIndex, 1);
    newEnvIds.splice(toIndex, 0, env);
    setSelectedEnvIds(newEnvIds);
  };

  const handleAddDetail = () => {
    if (!selectedAppId) {
      message.error('请选择应用');
      return;
    }

    if (!selectedVersion) {
      message.error('请选择版本');
      return;
    }

    // 获取应用名称
    const app = apps.find(a => a.id === selectedAppId);
    if (!app) return;

    // 为每个选中的环境都添加该应用，但仅限于该应用在该环境有部署配置的环境
    const appsArray = Array.isArray(deployStore.records) 
      ? deployStore.records 
      : Object.values(deployStore.records || {});
    
    const newDetails = [];
    selectedEnvIds.forEach((envId, idx) => {
      // 检查该环境是否有该应用的部署配置
      const hasDeploy = appsArray.some(
        app => app.deploys?.some(d => d.app_id === selectedAppId && d.env_id === envId)
      );

      if (!hasDeploy) {
        return; // 跳过没有部署配置的环境
      }

      // 检查是否已经添加过这个应用在这个环境
      if (!details.some(d => d.app_id === selectedAppId && d.env_id === envId)) {
        newDetails.push({
          app_id: selectedAppId,
          env_id: envId,
          app_name: app.name,
          version: selectedVersion,
          sequence: (details.length + idx + 1),
          key: `${Date.now()}_${envId}`
        });
      }
    });

    if (newDetails.length === 0) {
      message.warning('该应用在所有环境中都已添加或无部署配置');
      return;
    }

    setDetails([...details, ...newDetails]);
    setSelectedAppId(undefined);
    setSelectedVersion(undefined);
    message.success(`成功添加 ${newDetails.length} 条记录`);
  };

  const handleRemoveDetail = (key) => {
    setDetails(details.filter(d => d.key !== key));
  };

  // 切换某个应用在某个环境的选中状态
  const handleToggleEnv = (appId, appName, envId, checked) => {
    // 先基于当前 details 计算新的 details，确保同步更新 selectedAppsMap
    const appsArray = Array.isArray(deployStore.records) ? deployStore.records : Object.values(deployStore.records || {});
    const exists = details.some(d => d.app_id === appId && d.env_id === envId);
    if (checked) {
      if (exists) return;
      const hasDeploy = appsArray.some(app => app.deploys?.some(d => d.app_id === appId && d.env_id === envId));
      if (!hasDeploy) {
        message.warning('该应用在该环境没有部署配置');
        return;
      }

      const versionFromMap = selectedAppsMap[appId]?.version;
      const sameApp = details.find(d => d.app_id === appId);
      const version = versionFromMap || (sameApp ? sameApp.version : '');

      const newDetails = [...details, {
        app_id: appId,
        env_id: envId,
        app_name: appName,
        version,
        sequence: details.length + 1,
        key: `${Date.now()}_${envId}`
      }];
      setDetails(newDetails);

      // 自动将该应用标记为已选并防抖拉取版本
      setSelectedAppsMap(prev => {
        const next = { ...prev };
        if (!next[appId]) {
          next[appId] = { selected: true, version: '', availableVersions: [], loading: true };
        } else {
          next[appId].selected = true;
          next[appId].loading = true;
        }
        if (!next[appId].selectedOrder) {
          const existing = Object.values(next).map(x => x && x.selectedOrder).filter(Boolean);
          next[appId].selectedOrder = existing.length ? Math.max(...existing) + 1 : 1;
        }
        return next;
      });

      // 使用与 handleToggleApp 相同的防抖逻辑
      if (fetchDebounceTimers.current[appId]) {
        clearTimeout(fetchDebounceTimers.current[appId]);
      }
      fetchDebounceTimers.current[appId] = setTimeout(() => {
        const fetchKey = Date.now() + '_' + Math.random();
        setSelectedAppsMap(prev => (prev[appId] ? { ...prev, [appId]: { ...prev[appId], fetchKey } } : prev));
        fetchVersionsForApp(appId, appName, fetchKey);
      }, 200);
    } else {
      const newDetails = details.filter(d => !(d.app_id === appId && d.env_id === envId));
      setDetails(newDetails);
      // 如果该应用在任何环境都没有被选中，则移除其 selected 状态
      const stillHas = newDetails.some(d => d.app_id === appId);
      if (!stillHas) {
        setSelectedAppsMap(prev => {
          const next = { ...prev };
          delete next[appId];
          return next;
        });
      }
      // 取消时清除防抖定时器
      if (fetchDebounceTimers.current[appId]) {
        clearTimeout(fetchDebounceTimers.current[appId]);
        delete fetchDebounceTimers.current[appId];
      }
    }
  };

  // 切换应用是否作为迭代发布应用（激活版本选择）
  // 增加防抖，避免频繁选中/取消时重复请求版本
  const fetchDebounceTimers = useRef({});
  const handleToggleApp = (appId, appName, checked) => {
    setSelectedAppsMap(prev => {
      const next = { ...prev };
      if (checked) {
        next[appId] = next[appId] || { selected: true, version: '', availableVersions: [], loading: true };
        next[appId].selected = true;
        if (!next[appId].selectedOrder) {
          const existing = Object.values(next).map(x => x && x.selectedOrder).filter(Boolean);
          next[appId].selectedOrder = existing.length ? Math.max(...existing) + 1 : 1;
        }
        // 防抖：如有定时器先清除
        if (fetchDebounceTimers.current[appId]) {
          clearTimeout(fetchDebounceTimers.current[appId]);
        }
        // 200ms防抖
        fetchDebounceTimers.current[appId] = setTimeout(() => {
          const fetchKey = Date.now() + '_' + Math.random();
          setSelectedAppsMap(prev2 => {
            if (prev2[appId]) {
              return { ...prev2, [appId]: { ...prev2[appId], fetchKey } };
            }
            return prev2;
          });
          fetchVersionsForApp(appId, appName, fetchKey);
        }, 200);
        // 自动勾选该应用在有配置的环境
        const appsArray = Array.isArray(deployStore.records) ? deployStore.records : Object.values(deployStore.records || {});
        const newEnvDetails = [];
        selectedEnvIds.forEach(envId => {
          const hasDeploy = appsArray.some(app => app.deploys?.some(d => d.app_id === appId && d.env_id === envId));
          if (hasDeploy) {
            if (!details.some(d => d.app_id === appId && d.env_id === envId)) {
              newEnvDetails.push({
                app_id: appId,
                env_id: envId,
                app_name: appName,
                version: next[appId].version || '',
                sequence: details.length + newEnvDetails.length + 1,
                key: `${Date.now()}_${envId}_${newEnvDetails.length}`
              });
            }
          }
        });
        if (newEnvDetails.length > 0) {
          setDetails(prev => [...prev, ...newEnvDetails]);
        }
      } else {
        if (next[appId]) delete next[appId];
        setDetails(prevDetails => prevDetails.filter(d => d.app_id !== appId));
        if (fetchDebounceTimers.current[appId]) {
          clearTimeout(fetchDebounceTimers.current[appId]);
          delete fetchDebounceTimers.current[appId];
        }
      }
      return next;
    });
  };

  // fetchVersionsForApp 增加raceKey，防止异步覆盖
  const fetchVersionsForApp = async (appId, appName, fetchKey) => {
    if (!selectedEnvIds || selectedEnvIds.length === 0) return;
    setVersionLoading(true);
    try {
      const appsArray = Array.isArray(deployStore.records) ? deployStore.records : Object.values(deployStore.records || {});
      let deployId = null;
      const firstEnvId = selectedEnvIds[0];
      for (const app of appsArray) {
        if (app.deploys && Array.isArray(app.deploys)) {
          const deploy = app.deploys.find(d => d.env_id === firstEnvId && d.app_id === appId);
          if (deploy) { deployId = deploy.id; break; }
        }
      }
      if (!deployId) {
        for (const envId of selectedEnvIds) {
          for (const app of appsArray) {
            if (app.deploys && Array.isArray(app.deploys)) {
              const deploy = app.deploys.find(d => d.env_id === envId && d.app_id === appId);
              if (deploy) { deployId = deploy.id; break; }
            }
          }
          if (deployId) break;
        }
      }
      if (!deployId) {
        message.error(`${appName} 在所有发布环境中都没有部署配置，无法获取版本`);
        setVersionLoading(false);
        setSelectedAppsMap(prev => {
          // 只更新当前fetchKey对应的，合并保留已有字段（避免覆盖 selectedOrder 等）
          if (prev[appId]?.fetchKey === fetchKey) {
            return { ...prev, [appId]: { ...(prev[appId] || {}), selected: true, availableVersions: [], version: '', loading: false } };
          }
          return prev;
        });
        return;
      }
      const response = await http.get(`/api/app/deploy/${deployId}/versions/`);
      if (response.error) {
        message.error(response.error);
        setVersionLoading(false);
        return;
      }
      const responseData = response.data || response;
      const tags = responseData.tags || {};
      const versionList = Object.entries(tags).map(([name, info]) => ({ name, id: info.id, author: info.author, date: info.date, message: info.message }));
      setSelectedAppsMap(prev => {
        // 只更新当前fetchKey对应的，合并保留已有字段（避免覆盖 selectedOrder 等）
        if (prev[appId]?.fetchKey === fetchKey) {
          const next = { ...prev, [appId]: { ...(prev[appId] || {}), selected: true, availableVersions: versionList, version: versionList[0]?.name || '', loading: false } };
          // 如果已经有 details，更新它们的 version
          setDetails(prevDetails => prevDetails.map(d => d.app_id === appId ? { ...d, version: next[appId].version } : d));
          return next;
        }
        return prev;
      });
    } catch (error) {
      console.error('获取版本失败:', error);
      message.error('获取版本失败');
    } finally {
      setVersionLoading(false);
    }
  };

  const handleOk = () => {
    form.validateFields().then(() => {
      // 按照环境顺序 + 应用顺序生成 sequence
      // 先按环境分组，然后在每个环境内按应用顺序排序
      const sortedDetails = [];
      let seq = 1;
      selectedEnvIds.forEach(envId => {
        // 获取当前环境下的所有应用，按 selectedAppsMap 的 selectedOrder 排序
        const envDetails = details
          .filter(d => d.env_id === envId)
          .sort((a, b) => {
            const orderA = selectedAppsMap[a.app_id]?.selectedOrder || Number.MAX_SAFE_INTEGER;
            const orderB = selectedAppsMap[b.app_id]?.selectedOrder || Number.MAX_SAFE_INTEGER;
            return orderA - orderB;
          });
        envDetails.forEach(d => {
          sortedDetails.push({
            app_id: d.app_id,
            env_id: d.env_id,
            version: d.version,
            sequence: seq++
          });
        });
      });

      const payload = {
        ...form.getFieldsValue(),
        env_ids: selectedEnvIds,
        details: sortedDetails
      };

      // 编辑模式需要传递 id
      if (isEdit && store.record?.id) {
        payload.id = store.record.id;
      }

      const request = isEdit ? store.updateRecord(payload) : store.addRecord(payload);
      request
        .then(() => {
          store.formVisible = false;
          store.record = {};
          message.success(isEdit ? '迭代更新成功' : '迭代创建成功');
          store.fetchRecords();
        })
        .catch(err => {
          message.error(err.message || '操作失败');
        });
    });
  };

  // 构建矩阵形式的发布详情：每行一个应用，每列一个环境
  const allEnvIds = selectedEnvIds || [];
  const envIdToName = (envId) => envStore.records?.find(e => e.id === envId)?.name || envId;

  // 预计算 deploy 存在性，deployStore.records 可能是数组或对象
  const appsArrayForDeploy = Array.isArray(deployStore.records) ? deployStore.records : Object.values(deployStore.records || {});

  // 检查应用是否在任何选定环境中有配置
  const hasDeployInAnySelectedEnv = (appId) => {
    return allEnvIds.some(envId => 
      appsArrayForDeploy.some(app => app.deploys?.some(d => d.app_id === appId && d.env_id === envId))
    );
  };

  // 应用列表：按 tag、搜索名称、显示模式筛选，且只显示在选定环境中有配置的应用
  const appOrder = apps
    .filter(a => {
      if (selectedTag === 'ALL') return true;
      // rel_tags 是应用关联的标签数组，可能包含 tag.id 或 tag.key
      // 需要查找 tagList 中 key 或 id 匹配 selectedTag 的标签
      const appTags = a.rel_tags || [];
      // 直接检查是否包含 selectedTag（作为 key）
      if (appTags.includes(selectedTag)) return true;
      // 如果 selectedTag 是 tag.key，检查 appTags 中是否有对应 tag 的 id
      const matchedTag = tagList.find(t => t.key === selectedTag);
      if (matchedTag && appTags.includes(matchedTag.id)) return true;
      return false;
    })
    .filter(a => searchAppName === '' || a.name.toLowerCase().includes(searchAppName.toLowerCase()))
    .filter(a => showMode === 'all' || selectedAppsMap[a.id]?.selected)
    .filter(a => hasDeployInAnySelectedEnv(a.id))
    .map(a => ({ id: a.id, name: a.name, selectedOrder: selectedAppsMap[a.id]?.selectedOrder || Number.MAX_SAFE_INTEGER }))
    .sort((x, y) => {
      if (x.selectedOrder !== y.selectedOrder) return x.selectedOrder - y.selectedOrder;
      return String(x.name).localeCompare(String(y.name));
    })
    .map(a => ({ id: a.id, name: a.name }));

  const transformedDetails = appOrder.map((a, idx) => {
    const row = {
      key: a.id,
      sequence: idx + 1,
      app_name: a.name,
      app_id: a.id
    };
    allEnvIds.forEach(envId => {
      const detail = details.find(d => d.app_id === a.id && d.env_id === envId);
      row[envId] = detail || null;
      // 是否存在部署配置
      const hasDeploy = appsArrayForDeploy.some(appItem => appItem.deploys?.some(d => d.app_id === a.id && d.env_id === envId));
      row[`hasDeploy_${envId}`] = !!hasDeploy;
    });
    // 行版本：取该应用第一个存在的版本作为行版本
    const firstDetail = details.find(d => d.app_id === a.id && d.version);
    row.rowVersion = firstDetail ? firstDetail.version : (selectedAppsMap[a.id]?.version || '');
    row.selected = !!selectedAppsMap[a.id]?.selected;
    return row;
  });

    // 通过上移/下移按钮调整应用顺序（方案 A）
    const moveAppOrder = (appId, direction) => {
      const order = transformedDetails.map(d => d.app_id);
      const idx = order.indexOf(appId);
      if (idx === -1) return;
      const newIdx = direction === 'up' ? Math.max(0, idx - 1) : Math.min(order.length - 1, idx + 1);
      if (newIdx === idx) return;
      const newOrder = order.slice();
      const [item] = newOrder.splice(idx, 1);
      newOrder.splice(newIdx, 0, item);

      // 重新为 details 中对应的 app 赋序号（按 newOrder 索引）
      setDetails(prev => {
        const updated = prev.map(d => ({ ...d }));
        newOrder.forEach((aid, i) => {
          updated.forEach(rec => {
            if (rec.app_id === aid) rec.sequence = i + 1;
          });
        });
        return updated;
      });
      // 同步更新 selectedAppsMap 的 selectedOrder（若存在）
      setSelectedAppsMap(prev => {
        const next = { ...prev };
        newOrder.forEach((aid, i) => {
          if (next[aid]) next[aid].selectedOrder = i + 1;
        });
        return next;
      });
    };

  // 批量全选/取消全选处理，防止频繁点击导致状态错乱和UI卡死


  // 构建列：序号、应用名、每个环境列
  const detailColumns = [
    {
      title: '#',
      dataIndex: 'sequence',
      width: 90,
      fixed: 'left',
      render: (val, record) => {
        if (!record.selected) {
          return <span style={{ color: '#bfbfbf' }}>{val}</span>;
        }
        return (
          <Space size={4}>
            <Button size="small" type="text" icon={<ArrowUpOutlined />} onClick={(e) => { e.stopPropagation(); moveAppOrder(record.app_id, 'up'); }} />
            <Button size="small" type="text" icon={<ArrowDownOutlined />} onClick={(e) => { e.stopPropagation(); moveAppOrder(record.app_id, 'down'); }} />
            <span style={{ fontWeight: 600, color: '#1890ff' }}>{val}</span>
          </Space>
        );
      }
    },
    {
      title: '选择',
      dataIndex: 'selected',
      key: 'selected',
      width: 60,
      fixed: 'left',
      render: (v, record) => (
        <Checkbox
          checked={!!record.selected}
          onChange={(e) => handleToggleApp(record.app_id, record.app_name, e.target.checked)}
        />
      )
    },
    {
      title: '应用名称',
      dataIndex: 'app_name',
      width: 180,
      fixed: 'left',
      render: (text, record) => (
        <Space>
          <AppstoreOutlined style={{ color: record.selected ? '#1890ff' : '#bfbfbf' }} />
          <span
            style={{ cursor: 'pointer', fontWeight: record.selected ? 500 : 400, color: record.selected ? '#1890ff' : 'inherit' }}
            onClick={() => handleToggleApp(record.app_id, record.app_name, !record.selected)}
          >
            {text}
          </span>
        </Space>
      )
    },
    {
      title: '版本',
      dataIndex: 'rowVersion',
      key: 'rowVersion',
      width: 200,
      render: (v, record) => {
        const map = selectedAppsMap[record.app_id] || { availableVersions: [], version: '', loading: false };
        
        // 检查该应用是否有任何环境已发布成功
        const hasPublishedInAnyEnv = details.some(d => d.app_id === record.app_id && d.status === '2');
        
        if (!record.selected) {
          return map.version ? <Tag color="default">{map.version}</Tag> : <span style={{ color: '#d9d9d9' }}>—</span>;
        }
        
        // 如果已发布成功，只显示版本号，不允许修改
        if (hasPublishedInAnyEnv) {
          return (
            <Tooltip title="已有环境发布成功，版本不可修改">
              <Tag color="success" icon={<CheckCircleOutlined />}>{map.version || '-'}</Tag>
            </Tooltip>
          );
        }
        
        if (map.loading) {
          return <span style={{ color: '#bbb' }}>加载中...</span>;
        }
        if (!Array.isArray(map.availableVersions) || map.availableVersions.length === 0) {
          return (
            <Button 
              type="link" 
              size="small" 
              onClick={() => {
                // 点击时重新获取版本
                const appName = record.app_name;
                const appId = record.app_id;
                fetchVersionsForApp(appId, appName);
              }}
              style={{ padding: 0 }}
            >
              点击获取版本
            </Button>
          );
        }
        return (
          <Select
            style={{ width: '100%' }}
            size="small"
            value={map.version || undefined}
            onChange={(val) => {
              setSelectedAppsMap(prev => ({ ...prev, [record.app_id]: { ...(prev[record.app_id] || {}), version: val } }));
              setDetails(prev => prev.map(d => d.app_id === record.app_id ? { ...d, version: val } : d));
            }}
            placeholder="选择版本"
            onDropdownVisibleChange={(open) => {
              // 下拉框打开时，如果版本列表为空，自动获取
              if (open && (!map.availableVersions || map.availableVersions.length === 0)) {
                fetchVersionsForApp(record.app_id, record.app_name);
              }
            }}
          >
            {/* 确保当前选中的版本在选项中，避免 label 不匹配警告 */}
            {map.version && !map.availableVersions.some(v => v.name === map.version) && (
              <Select.Option key="current" value={map.version}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>{map.version}</span>
                  <span style={{ color: '#999', fontSize: 11 }}>当前版本</span>
                </div>
              </Select.Option>
            )}
            {map.availableVersions.map((ver, idx) => (
              <Select.Option key={idx} value={ver.name}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>{ver.name}</span>
                  <span style={{ color: '#999', fontSize: 11 }}>{ver.author} {ver.date}</span>
                </div>
              </Select.Option>
            ))}
          </Select>
        );
      }
    },
    ...allEnvIds.map((envId) => ({
      title: <Tag color="processing" style={{ margin: 0 }}>{envIdToName(envId)}</Tag>,
      dataIndex: envId,
      key: envId,
      align: 'center',
      width: 100,
      render: (cell, record) => {
        const checked = !!cell;
        const hasDeploy = !!record[`hasDeploy_${envId}`];
        return (
          <Tooltip title={hasDeploy ? (checked ? '取消选择' : '选择此环境') : '无部署配置'}>
            <Checkbox
              checked={checked}
              disabled={!hasDeploy}
              onChange={(e) => { if (hasDeploy) handleToggleEnv(record.app_id, record.app_name, envId, e.target.checked); }}
            />
          </Tooltip>
        );
      }
    }))
  ];

  // （已移除拖拽排序逻辑）

  return (
    <Modal
      title={
        <Space>
          <RocketOutlined style={{ color: '#1890ff' }} />
          <span>{isEdit ? '编辑迭代' : '新建迭代'}</span>
        </Space>
      }
      visible={store.formVisible}
      onCancel={() => {
        store.formVisible = false;
        store.record = {};
        setDetails([]);
        setSelectedEnvIds([]);
        setSelectedAppId(undefined);
        setSelectedVersion(undefined);
        setAvailableVersions([]);
      }}
      onOk={handleOk}
      width={1200}
      confirmLoading={initLoading}
      okText={isEdit ? '保存' : '创建'}
      cancelText="取消"
      bodyStyle={{ padding: '16px 24px', maxHeight: '80vh', overflowY: 'auto' }}
    >
      <Spin spinning={initLoading}>
        <Form
          form={form}
          layout="vertical"
          initialValues={store.record || {}}
        >
          {/* 基本信息卡片 */}
          <Card 
            title={<Space><AppstoreOutlined />基本信息</Space>}
            size="small" 
            style={{ marginBottom: 16, borderRadius: 8 }}
            headStyle={{ background: '#fafafa', borderRadius: '8px 8px 0 0' }}
          >
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="name"
                  label="迭代名称"
                  rules={[{required: true, message: '请输入迭代名称'}]}
                  style={{ marginBottom: 12 }}
                >
                  <Input placeholder="请输入迭代名称" ref={nameInputRef} prefix={<RocketOutlined style={{ color: '#bfbfbf' }} />} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="desc"
                  label="描述"
                  style={{ marginBottom: 12 }}
                >
                  <Input placeholder="请输入迭代描述" />
                </Form.Item>
              </Col>
            </Row>
          </Card>

          {/* 发布环境卡片 */}
          <Card 
            title={<Space><EnvironmentOutlined />发布环境 <Badge count={selectedEnvIds.length} style={{ backgroundColor: '#1890ff' }} /></Space>}
            size="small" 
            style={{ marginBottom: 16, borderRadius: 8 }}
            headStyle={{ background: '#fafafa', borderRadius: '8px 8px 0 0' }}
          >
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              flexWrap: 'wrap',
              padding: '12px',
              backgroundColor: '#f9f9f9',
              borderRadius: '6px',
              minHeight: 50
            }}>
              {selectedEnvIds.length === 0 ? (
                <Alert message="请在下方选择要发布的环境" type="info" showIcon style={{ padding: '4px 12px' }} />
              ) : (
                selectedEnvIds.map((envId, idx) => {
                  const env = envStore.records?.find(e => e.id === envId);
                  const isProd = env?.prod;
                  return (
                    <Tag
                      key={envId}
                      color={isProd ? '#f50' : 'default'}
                      style={{
                        padding: '4px 8px',
                        fontSize: '13px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        borderRadius: '4px'
                      }}
                    >
                      <span style={{ fontWeight: 600, marginRight: 4 }}>{idx + 1}.</span>
                      {isProd && <span style={{ fontSize: 11, marginRight: 2 }}>🔴</span>}
                      <span>{env?.name}</span>
                      <Space size={2}>
                        {idx > 0 && (
                          <Tooltip title="上移">
                            <ArrowUpOutlined
                              style={{ cursor: 'pointer', fontSize: 12 }}
                              onClick={() => moveEnv(idx, idx - 1)}
                            />
                          </Tooltip>
                        )}
                        {idx < selectedEnvIds.length - 1 && (
                          <Tooltip title="下移">
                            <ArrowDownOutlined
                              style={{ cursor: 'pointer', fontSize: 12 }}
                              onClick={() => moveEnv(idx, idx + 1)}
                            />
                          </Tooltip>
                        )}
                        <Tooltip title="移除">
                          <CloseOutlined
                            style={{ cursor: 'pointer', fontSize: 12 }}
                            onClick={() => removeEnv(envId)}
                          />
                        </Tooltip>
                      </Space>
                    </Tag>
                  );
                })
              )}
            </div>
            <Select
              placeholder="点击添加发布环境"
              style={{ width: '100%', marginTop: 8 }}
              value={undefined}
              onChange={(envId) => {
                if (!selectedEnvIds.includes(envId)) {
                  setSelectedEnvIds([...selectedEnvIds, envId]);
                }
              }}
              suffixIcon={<PlusOutlined />}
            >
              {envStore.records?.map(env => (
                <Select.Option 
                  key={env.id} 
                  value={env.id} 
                  disabled={selectedEnvIds.includes(env.id)}
                >
                  {env.prod && <Tag color="error" style={{ marginRight: 4 }}>生产</Tag>}
                  {env.name} {selectedEnvIds.includes(env.id) && '✓'}
                </Select.Option>
              ))}
            </Select>
          </Card>

          {/* 发布项详情卡片 */}
          <Card 
            title={
              <Space>
                <AppstoreOutlined />
                发布项详情 
                <Badge count={Object.keys(selectedAppsMap).filter(k => selectedAppsMap[k]?.selected).length} style={{ backgroundColor: '#52c41a' }} overflowCount={999} />
              </Space>
            }
            size="small"
            style={{ borderRadius: 8 }}
            headStyle={{ background: '#fafafa', borderRadius: '8px 8px 0 0' }}
          >
            {/* 筛选栏 */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              marginBottom: 12,
              padding: '12px',
              backgroundColor: '#f9f9f9',
              borderRadius: '6px'
            }}>
              <Input
                placeholder="搜索应用"
                allowClear
                style={{ width: 200 }}
                value={searchAppName}
                onChange={(e) => setSearchAppName(e.target.value)}
                prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
              />
              <Tabs
                activeKey={selectedTag}
                onChange={(v) => setSelectedTag(v)}
                style={{ flex: 1, marginBottom: 0 }}
                tabBarStyle={{ marginBottom: 0 }}
                size="small"
              >
                <Tabs.TabPane tab="全部应用" key="ALL" />
                {tagList.map(t => (
                  <Tabs.TabPane tab={t.name} key={t.key} />
                ))}
              </Tabs>
              <Button.Group size="small">
                <Button
                  type={showMode === 'all' ? 'primary' : 'default'}
                  onClick={() => setShowMode('all')}
                >
                  全部
                </Button>
                <Button
                  type={showMode === 'selected' ? 'primary' : 'default'}
                  onClick={() => setShowMode('selected')}
                >
                  已勾选
                </Button>
              </Button.Group>
            </div>

            {/* 应用列表 */}
            <Table
              columns={detailColumns}
              dataSource={transformedDetails}
              rowKey="key"
              pagination={transformedDetails.length > 20 ? { pageSize: 20, size: 'small', showTotal: (total) => `共 ${total} 个应用` } : false}
              size="small"
              scroll={{ x: Math.max(800, allEnvIds.length * 150), y: 400 }}
              rowClassName={(record) => record.selected ? 'selected-row' : ''}
            />
          </Card>
        </Form>
      </Spin>
    </Modal>
  )
}

export default observer(FormComponent)
